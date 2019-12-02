/*
 * HDMI2PCIe driver
 *
 * Copyright (C) 2018 / LambdaConcept / ramtin@lambdaconcept.com
 * Copyright (C) 2018 / LambdaConcept / po@lambdaconcept.com
 * Copyright (C) 2018 / EnjoyDigital  / florent@enjoy-digital.fr
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.

 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/types.h>
#include <linux/ioctl.h>
#include <linux/init.h>
#include <linux/errno.h>
#include <linux/mm.h>
#include <linux/fs.h>
#include <linux/mmtimer.h>
#include <linux/miscdevice.h>
#include <linux/posix-timers.h>
#include <linux/interrupt.h>
#include <linux/time.h>
#include <linux/math64.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/pci.h>
#include <linux/pci_regs.h>
#include <linux/delay.h>
#include <linux/wait.h>
#include <linux/log2.h>
#include <linux/cdev.h>

#define NETV2_NAME "netv2"
#define NETV2_MINOR_COUNT 32
#define NETV2_BUF_SIZE 1*1024*1024

#define PCIE_FPGA_VENDOR_ID 0x10ee
#define PCIE_FPGA_DEVICE_ID 0x7022

struct netv2_device {
    struct pci_dev  *dev;
    struct cdev *cdev;
    resource_size_t bar0_size;
    phys_addr_t bar0_phys_addr;
    uint8_t *bar0_addr; /* virtual address of BAR0 */
    int minor_base;
};

static int netv2_major;
static int netv2_minor_idx;
static struct class* netv2_class;
static dev_t netv2_dev_t;

struct netv2_device *netv2_g;

static int netv2_open(struct inode *inode, struct file *file)
{
    file->private_data = netv2_g;

    return 0;
}

static int netv2_release(struct inode *inode, struct file *file)
{
    return 0;
}

static ssize_t netv2_read(struct file *file, char __user *data, size_t size, loff_t *offset)
{
    int i;
    struct netv2_device *s = file->private_data;
    uint32_t *buf;
    buf = kzalloc(NETV2_BUF_SIZE, GFP_KERNEL);

    if(!buf){
        printk(KERN_ERR "failed to allocate buffer\n");
        return -ENOMEM;
    }

    for (i = 0; i < size;) {
        int xfer_size = NETV2_BUF_SIZE < (size - i) ? NETV2_BUF_SIZE : (size - i);

        memcpy_fromio(buf, s->bar0_addr + i + *offset, xfer_size);

        if(copy_to_user(data + i, buf, xfer_size)){
            kfree(buf);
            printk(KERN_ERR "copy_to_user failed\n");
            return -EFAULT;
        }

	i += xfer_size;
    }

    kfree(buf);

    *offset += size;

    return size;
}

static ssize_t netv2_write(struct file *file, const char __user *data, size_t size, loff_t *offset)
{
    int i;
    struct netv2_device *s = file->private_data;
    uint32_t *buf;

    buf = kzalloc(NETV2_BUF_SIZE, GFP_KERNEL);

    if(!buf){
        printk(KERN_ERR "failed to allocate buffer\n");
        return -ENOMEM;
    }

    for (i = 0; i < size;) {
        int xfer_size = NETV2_BUF_SIZE < (size - i) ? NETV2_BUF_SIZE : (size - i);

        if(copy_from_user(buf, data + i, xfer_size)){
            kfree(buf);
            printk(KERN_ERR "copy_from_user failed\n");
            return -EFAULT;
        }

        memcpy_toio(s->bar0_addr + i + *offset, buf, xfer_size);

	i += xfer_size;
    }

    kfree(buf);

    *offset += size;

    return size;
}

static struct file_operations netv2_fops = {
    .owner = THIS_MODULE,
    .open = netv2_open,
    .release = netv2_release,
    .read = netv2_read,
    .write = netv2_write,
    .llseek = generic_file_llseek,
};

static int netv2_alloc_chdev(struct netv2_device *s)
{
    int ret;
    int index;

    index = netv2_minor_idx;
    s->minor_base = netv2_minor_idx;
    s->cdev = cdev_alloc();
    if(!s->cdev) {
        ret = -ENOMEM;
        printk(KERN_ERR NETV2_NAME " Failed to allocate cdev\n");
        goto fail_alloc;
    }

    cdev_init(s->cdev, &netv2_fops);
    ret = cdev_add(s->cdev, MKDEV(netv2_major, index), 1);
    if(ret < 0) {
        printk(KERN_ERR NETV2_NAME " Failed to allocate cdev\n");
        goto fail_alloc;
    }

    printk(KERN_INFO NETV2_NAME " Creating /dev/netv2%d\n", index);
    if(!device_create(netv2_class, NULL, MKDEV(netv2_major, index), NULL, "netv2%d", index)) {
        ret = -EINVAL;
        printk(KERN_ERR NETV2_NAME " Failed to create device\n");
        goto fail_create;
    }

    return 0;

fail_create:
    device_destroy(netv2_class, MKDEV(netv2_major, index));

fail_alloc:
    if(s->cdev) {
        cdev_del(s->cdev);
        s->cdev=NULL;
    }

    return ret;
}

static void netv2_free_chdev(struct netv2_device *s)
{
    device_destroy(netv2_class, MKDEV(netv2_major, s->minor_base));
    cdev_del(s->cdev);
    s->cdev=NULL;
}

static int netv2_pci_probe(struct pci_dev *dev, const struct pci_device_id *id)
{
    int ret=0;
    uint8_t rev_id;

    struct netv2_device *netv2_dev = NULL;

    printk(KERN_INFO NETV2_NAME " \e[1m[Probing device]\e[0m\n");

    netv2_dev = kzalloc(sizeof(struct netv2_device), GFP_KERNEL);
    if(!netv2_dev) {
        printk(KERN_ERR NETV2_NAME " Cannot allocate memory\n");
        ret = -ENOMEM;
        goto fail1;
    }

    pci_set_drvdata(dev, netv2_dev);
    netv2_dev->dev = dev;
    netv2_g = netv2_dev;

    ret = pci_enable_device(dev);
    if (ret != 0) {
        printk(KERN_ERR NETV2_NAME " Cannot enable device\n");
        goto fail1;
    }

    /* check device version */
    pci_read_config_byte(dev, PCI_REVISION_ID, &rev_id);
    if (rev_id != 1) {
        printk(KERN_ERR NETV2_NAME " Unsupported device version %d\n", rev_id);
        goto fail2;
    }

    if (pci_request_regions(dev, NETV2_NAME) < 0) {
        printk(KERN_ERR NETV2_NAME " Could not request regions\n");
        goto fail2;
    }


    /* check bar0 config */
    if (!(pci_resource_flags(dev, 0) & IORESOURCE_MEM)) {
        printk(KERN_ERR NETV2_NAME " Invalid BAR0 configuration\n");
        goto fail3;
    }

    netv2_dev->bar0_addr = pci_ioremap_bar(dev, 0);
    netv2_dev->bar0_size = pci_resource_len(dev, 0);
    netv2_dev->bar0_phys_addr = pci_resource_start(dev, 0);
    if (!netv2_dev->bar0_addr) {
        printk(KERN_ERR NETV2_NAME " Could not map BAR0\n");
        goto fail3;
    }

    pci_set_master(dev);
    ret = pci_set_dma_mask(dev, DMA_BIT_MASK(32));
    if (ret) {
        printk(KERN_ERR NETV2_NAME " Failed to set DMA mask\n");
        goto fail4;
    };

    ret = pci_enable_msi(dev);
    if (ret) {
        printk(KERN_ERR NETV2_NAME " Failed to enable MSI\n");
        goto fail4;
    }

    /* create all chardev in /dev */
    ret = netv2_alloc_chdev(netv2_dev);
    if(ret){
        printk(KERN_ERR NETV2_NAME "Failed to allocate character device\n");
        goto fail5;
    }

    printk(KERN_INFO NETV2_NAME " NeTV2 device probed\n");

    return 0;

fail5:
    pci_disable_msi(dev);
fail4:
    pci_iounmap(dev, netv2_dev->bar0_addr);
fail3:
    pci_release_regions(dev);
fail2:
    pci_disable_device(dev);
fail1:
    if(netv2_dev){
        kfree(netv2_dev);
    }
    return ret;
}

static void netv2_pci_remove(struct pci_dev *dev)
{
    struct netv2_device *netv2_dev;

    netv2_dev = pci_get_drvdata(dev);

    printk(KERN_INFO NETV2_NAME " \e[1m[Removing device]\e[0m\n");

    if(netv2_dev){
        netv2_free_chdev(netv2_dev);
    }

    pci_disable_msi(dev);
    if(netv2_dev)
        pci_iounmap(dev, netv2_dev->bar0_addr);
    pci_disable_device(dev);
    pci_release_regions(dev);
    if(netv2_dev){
        kfree(netv2_dev);
    }
}

static const struct pci_device_id netv2_pci_ids[] = {
  { PCI_DEVICE(PCIE_FPGA_VENDOR_ID, PCIE_FPGA_DEVICE_ID ), },
  { 0, }
};
MODULE_DEVICE_TABLE(pci, netv2_pci_ids);

static struct pci_driver netv2_pci_driver = {
  .name = NETV2_NAME,
  .id_table = netv2_pci_ids,
  .probe = netv2_pci_probe,
  .remove = netv2_pci_remove,
};


static int __init netv2_module_init(void)
{
    int ret;

    netv2_class = class_create(THIS_MODULE, NETV2_NAME);
    if(!netv2_class) {
        ret = -EEXIST;
        printk(KERN_ERR NETV2_NAME " Failed to create class\n");
        goto fail_create_class;
    }

    ret = alloc_chrdev_region(&netv2_dev_t, 0, NETV2_MINOR_COUNT, NETV2_NAME);
    if(ret < 0) {
        printk(KERN_ERR NETV2_NAME " Could not allocate char device\n");
        goto fail_alloc_chrdev_region;
    }
    netv2_major = MAJOR(netv2_dev_t);
    netv2_minor_idx = MINOR(netv2_dev_t);

    ret = pci_register_driver(&netv2_pci_driver);
    if (ret < 0) {
        printk(KERN_ERR NETV2_NAME NETV2_NAME " Error while registering PCI driver\n");
        goto fail_register;
    }

    return 0;

fail_register:
    unregister_chrdev_region(netv2_dev_t, NETV2_MINOR_COUNT);
fail_alloc_chrdev_region:
    class_destroy(netv2_class);
fail_create_class:
    return ret;
}

static void __exit netv2_module_exit(void)
{
    pci_unregister_driver(&netv2_pci_driver);
    unregister_chrdev_region(netv2_dev_t, NETV2_MINOR_COUNT);
    class_destroy(netv2_class);
}


module_init(netv2_module_init);
module_exit(netv2_module_exit);

MODULE_LICENSE("GPL");
