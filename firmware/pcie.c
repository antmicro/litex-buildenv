#include "pcie.h"
#include "framebuffer.h"

unsigned int pcie_in_framebuffer_base(void) {
	return FRAMEBUFFER_BASE_PCIE;
}
