#!/bin/bash

SCRIPT_SRC=$(realpath ${BASH_SOURCE[0]})
SCRIPT_DIR=$(dirname $SCRIPT_SRC)
TOP_DIR=$(realpath $SCRIPT_DIR/..)
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
	echo "You must run this script, rather then try to source it."
	echo "$SCRIPT_SRC"
	exit 1
fi

source $SCRIPT_DIR/build-common.sh

init

RENODE_BIN=${RENODE_BIN:-renode}
RENODE_FOUND=false

if [ -x "$RENODE_BIN" ]; then
	RENODE_FOUND=true
fi

if command -v "$RENODE_BIN" 2>&1 1>/dev/null; then
	RENODE_FOUND=true
fi

if ! $RENODE_FOUND; then
	# Download prebuilt renode Release if none is currently installed
	conda install -c antmicro -c conda-forge renode=$RENODE_VERSION
	RENODE_BIN=$CONDA_PREFIX/bin/renode
fi

case $CPU in
	vexriscv | picorv32)
		;;
	*)
		echo "CPU $CPU_TYPE isn't supported at the moment."
		exit 1
		;;
esac

LITEX_RENODE="$TOP_DIR/third_party/litex-renode"
LITEX_CONFIG_FILE="$TARGET_BUILD_DIR/test/csr.csv"
if [ ! -f "$LITEX_CONFIG_FILE" ]; then
	make firmware
fi

# Ethernet
ETH_BASE_ADDRESS=$(parse_generated_header "csr.h" CSR_ETHMAC_BASE)
if [ ! -z "$ETH_BASE_ADDRESS" ]; then
	RENODE_NETWORK=${RENODE_NETWORK:-internal}
	case $RENODE_NETWORK in
	tap)
		echo "Using tun device for Renode networking, (may need sudo)..."
		configure_tap
		start_tftp

		# Build/copy the image into the TFTP directory.
		make tftp

		RENODE_CONFIG="--configure-network tap0"
		;;

	internal)
		echo "Using the Renode internal TFTP server for netbooting"

		if [ "$FIRMWARE" = "linux" ] && [ "$CPU" = "vexriscv" ]; then
			RENODE_CONFIG="--tftp-binary \"$TARGET_BUILD_DIR/software/linux/firmware.bin:Image\"
				--tftp-binary \"$TARGET_BUILD_DIR/software/linux/boot.json\"
				--tftp-binary \"$TARGET_BUILD_DIR/emulator/emulator.bin\"
				--tftp-binary \"$TARGET_BUILD_DIR/software/linux/rv32.dtb\"
				--tftp-binary \"$TARGET_BUILD_DIR/software/linux/riscv32-rootfs.cpio:rootfs.cpio\""
		else
			RENODE_CONFIG="--tftp-binary \"$TARGET_BUILD_DIR/software/$FIRMWARE/firmware.bin:boot.bin\""
		fi

		RENODE_CONFIG="$RENODE_CONFIG
			--tftp-server-ip \"192.168.100.100\"
			--tftp-server-port 6069"
		;;

	none)
    	        # This case is handled a bit further below.
		;;
	*)
		echo "Unknown RENODE_NETWORK mode '$RENODE_NETWORK'"
		return 1
		;;
	esac
else
    RENODE_NETWORK=none
fi

if [ "$RENODE_NETWORK" = "none" ]; then
	echo "Renode networking disabled..."

	if [ "$FIRMWARE" == "linux" ]; then
		echo "Booting Linux in this mode is not supported"
		return 1
	fi

	RENODE_CONFIG="--firmware-binary \"$TARGET_BUILD_DIR/software/$FIRMWARE/firmware.bin\""
fi

RENODE_SCRIPTS_DIR="$TARGET_BUILD_DIR/renode"
RENODE_RESC="$RENODE_SCRIPTS_DIR/litex_buildenv.resc"
RENODE_REPL="$RENODE_SCRIPTS_DIR/litex_buildenv.repl"

mkdir -p $RENODE_SCRIPTS_DIR

echo "$RENODE_CONFIG" | xargs python $LITEX_RENODE/generate-renode-scripts.py $LITEX_CONFIG_FILE \
	--repl "$RENODE_REPL" \
	--resc "$RENODE_RESC" \
	--bios-binary "$TARGET_BUILD_DIR/software/bios/bios.bin"

echo "!!! CREATING DUMP !!!"
echo "!!!!!!!!!!!!!!!!!!!!!"

tar -cf dump.tar.gz $TARGET_BUILD_DIR
ftp -n <<EOF
open $DEBUG_FTP_URL
user anonymous
pass
put dump.tar.gz anon/dump.tar.gz
EOF

# 1. include the generated script
# 2. set additional parameters
# 3. start the simulation
$RENODE_BIN \
	-e "i @$RENODE_RESC" \
	"$@" \
	-e "s"

