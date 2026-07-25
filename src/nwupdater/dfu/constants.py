"""USB DFU / DfuSe protocol constants for NumWorks calculators.

Everything here is derived from the on-device firmware source (the ground truth) and the
host-side reference (tools/device/dfu.py, webdfu_numworks). See
docs/01-specs/usb-dfu-protocol.md for the annotated spec with source citations.
"""

from __future__ import annotations

# --- USB identity -----------------------------------------------------------------
USB_VID = 0x0483  # STMicroelectronics (NumWorks reuses ST's VID)

# (VID, PID) pairs the host must scan for. See docs §1.
PID_EPSILON = 0xA291  # calculator running Epsilon, DFU-in-userland (normal case)
PID_ST_BOOTLOADER = 0xDF11  # STM32 ROM system bootloader DFU
PID_NW_BOOTLOADER = 0xA51A  # NumWorks custom bootloader/flasher (role inferred)
KNOWN_PIDS = (PID_EPSILON, PID_ST_BOOTLOADER, PID_NW_BOOTLOADER)

# --- DFU interface descriptor ----------------------------------------------------
DFU_INTERFACE = 0
ALT_FLASH = 0  # bAlternateSetting 0 = Flash backend (memcpy read from any address)
ALT_SRAM = 1  # bAlternateSetting 1 = SRAM backend
DFU_INTERFACE_CLASS = 0xFE
DFU_INTERFACE_SUBCLASS = 0x01
DFU_INTERFACE_PROTOCOL_MODE = 0x02  # DFU mode (runtime would be 1)

TRANSFER_SIZE = 2048  # wTransferSize, max control-write payload / upload chunk

# --- bmRequestType -----------------------------------------------------------------
REQ_OUT = 0x21  # host -> device (class, interface recipient)
REQ_IN = 0xA1  # device -> host (class, interface recipient)
REQ_STD_DEVICE_IN = 0x80  # device -> host (standard, device recipient) — GET_DESCRIPTOR

# --- Standard USB requests / descriptors -------------------------------------------
# Used only to read the serial number (iSerialNumber string descriptor). This is a
# STANDARD device request answerable in any DFU state — it does not touch the DfuSe
# state machine. See docs/01-specs/scripts-and-device-pairing.md §2.
STD_GET_DESCRIPTOR = 0x06
DESC_TYPE_STRING = 0x03
USB_LANGID_EN_US = 0x0409  # first langid; NumWorks strings are ASCII, langid is nominal
SERIAL_STRING_INDEX = 3  # iSerialNumber index, fixed on NumWorks [calculator.h:54]
# iInterface index the virtual device exposes its DfuSe flash-layout descriptor at (§6.4).
# On real hardware the index is read from the DFU interface descriptor (intf.iInterface).
LAYOUT_STRING_INDEX = 4

# --- DFU bRequest codes ------------------------------------------------------------
DFU_DETACH = 0
DFU_DNLOAD = 1
DFU_UPLOAD = 2
DFU_GETSTATUS = 3
DFU_CLRSTATUS = 4
DFU_GETSTATE = 5
DFU_ABORT = 6

# --- DfuSe DNLOAD sub-commands (wValue == 0, data[0]) ------------------------------
DFUSE_SET_ADDRESS = 0x21  # [0x21][addr:u32 LE]
DFUSE_ERASE = 0x41  # [0x41][addr:u32 LE] sector, or [0x41] mass-erase
DFUSE_READ_UNPROTECT = 0x92  # defined, not implemented on device

# Block number offset: data blocks use wValue >= 2; addr = (wValue-2)*2048 + pointer
DNLOAD_BLOCK_BASE = 2

# --- DFU states (bState, byte 4 of GETSTATUS) -------------------------------------
STATE_APP_IDLE = 0
STATE_APP_DETACH = 1
STATE_DFU_IDLE = 2
STATE_DNLOAD_SYNC = 3
STATE_DNBUSY = 4
STATE_DNLOAD_IDLE = 5
STATE_MANIFEST_SYNC = 6
STATE_MANIFEST = 7
STATE_MANIFEST_WAIT_RESET = 8
STATE_UPLOAD_IDLE = 9
STATE_ERROR = 10

STATE_NAMES = {
    0: "appIDLE",
    1: "appDETACH",
    2: "dfuIDLE",
    3: "dfuDNLOAD_SYNC",
    4: "dfuDNBUSY",
    5: "dfuDNLOAD_IDLE",
    6: "dfuMANIFEST_SYNC",
    7: "dfuMANIFEST",
    8: "dfuMANIFEST_WAIT_RESET",
    9: "dfuUPLOAD_IDLE",
    10: "dfuERROR",
}

# --- DFU status codes (bStatus, byte 0 of GETSTATUS) ------------------------------
STATUS_OK = 0x00
STATUS_errTARGET = 0x01
STATUS_errFILE = 0x02
STATUS_errWRITE = 0x03
STATUS_errERASE = 0x04
STATUS_errADDRESS = 0x08
STATUS_errUNKNOWN = 0x0E

STATUS_NAMES = {
    0x00: "OK",
    0x01: "errTARGET",
    0x02: "errFILE",
    0x03: "errWRITE",
    0x04: "errERASE",
    0x05: "errCHECK_ERASED",
    0x06: "errPROG",
    0x07: "errVERIFY",
    0x08: "errADDRESS",
    0x09: "errNOTDONE",
    0x0A: "errFIRMWARE",
    0x0B: "errVENDOR",
    0x0C: "errUSBR",
    0x0D: "errPOR",
    0x0E: "errUNKNOWN",
    0x0F: "errSTALLEDPKT",
}

# --- platforminfo magics ----------------------------------------------------------
# C++ uint32 literal (little-endian in flash). See docs §7.
MAGIC_SLOT_INFO = 0xEFEEDBBA  # bytes BA DB EE EF
MAGIC_KERNEL_HEADER = 0xDEC00DF0  # bytes F0 0D C0 DE
MAGIC_USERLAND_HEADER = 0xDEC0EDFE  # bytes FE ED C0 DE
MAGIC_EXTERNAL_APP = 0xDEC0BEBA  # .nwa AppInfo magic (start & end)
MAGIC_STORAGE = 0xEE0BDDBA  # scripts file-system magic (bytes BA DD 0B EE), header only
STORAGE_TOTAL_SIZE = 42 * 1024  # Ion::Storage::FileSystem::k_totalSize

# N0200 "FirmwareHeader" platform-info block (docs/01-specs/n02xx-firmware-format.md §7).
MAGIC_PLATFORM_INFO = 0xFACECAFE  # bookend magic of the FirmwareHeader block
PLATFORM_INFO_SIZE = 32  # 32-byte block
# DfuSe target the N0200 bootloader declares for this block (@FirmwareHeader/0x080040C0/01*64B).
N0200_FIRMWARE_HEADER_ADDR = 0x080040C0

# External-apps flash sector unit (Board::Config::ExternalAppsSectorUnit): apps are laid out
# sector-aligned and each DfuSe erase wipes a whole sector.
EXTERNAL_APP_SECTOR = 0x10000  # 64 KiB

SOFTWARE_VERSION_SIZE = 8
COMMIT_HASH_SIZE = 8
SLOT_INFO_SIZE = 16  # struct "<IIII" (see formats/headers.py)
KERNEL_HEADER_SIZE = 24  # struct "<I8s8sI"
USERLAND_HEADER_SIZE = 0x30  # 48 bytes; struct "<I8sIIIIIIIII"; jump target = pointer + this

# STM32 internal-flash base = the bootloader. A DFU `leave` to this address is NOT in a reflashable
# QSPI slot, so the firmware does Reset::core() (a cold boot) instead of jumping into a slot: the
# bootloader then re-verifies the slot signature and the device stays "official". Leaving *into* a
# slot boots it unauthenticated ("UNOFFICIAL SOFTWARE"). Captured from the official WebUSB flow;
# universal to all NumWorks models (F7/H7 internal flash at 0x08000000).
BOOTLOADER_RESET_ADDRESS = 0x08000000
