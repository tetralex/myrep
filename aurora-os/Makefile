# AuroraOS – Build-System (läuft in WSL2 / Linux)
#
#   make          -> baut build/aurora.iso
#   make run      -> startet die ISO in QEMU (UEFI)
#   make debug    -> startet QEMU angehalten mit GDB-Server auf Port 1234
#   make clean    -> räumt auf

ISO      := build/aurora.iso
KERNEL   := kernel/target/x86_64-aurora/release/kernel
LIMINE   := limine
# OVMF = UEFI-Firmware für QEMU (Paket „ovmf“)
OVMF     ?= /usr/share/OVMF/OVMF_CODE_4M.fd

QEMU_FLAGS := -M q35 -m 512M -serial stdio -no-reboot -no-shutdown \
              -drive if=pflash,format=raw,readonly=on,file=$(OVMF) \
              -cdrom $(ISO)

.PHONY: all kernel run run-bios debug clean distclean

all: $(ISO)

kernel:
	cd kernel && cargo build --release

# Limine-Binaries (vorkompiliert) einmalig herunterladen
$(LIMINE)/limine:
	git clone https://github.com/limine-bootloader/limine.git --branch=v11.x-binary --depth=1 $(LIMINE)
	$(MAKE) -C $(LIMINE)

$(ISO): kernel $(LIMINE)/limine limine.conf
	rm -rf build/iso_root
	mkdir -p build/iso_root/boot/limine build/iso_root/EFI/BOOT
	cp $(KERNEL) build/iso_root/boot/kernel
	cp limine.conf build/iso_root/boot/limine/
	cp $(LIMINE)/limine-bios.sys $(LIMINE)/limine-bios-cd.bin \
	   $(LIMINE)/limine-uefi-cd.bin build/iso_root/boot/limine/
	cp $(LIMINE)/BOOTX64.EFI build/iso_root/EFI/BOOT/
	xorriso -as mkisofs -R -r -J \
	    -b boot/limine/limine-bios-cd.bin -no-emul-boot -boot-load-size 4 -boot-info-table \
	    -hfsplus -apm-block-size 2048 \
	    --efi-boot boot/limine/limine-uefi-cd.bin -efi-boot-part --efi-boot-image \
	    --protective-msdos-label build/iso_root -o $(ISO) 2>/dev/null
	./$(LIMINE)/limine bios-install $(ISO) >/dev/null 2>&1
	@echo ">> fertig: $(ISO)"

run: $(ISO)
	qemu-system-x86_64 $(QEMU_FLAGS)

run-bios: $(ISO)
	qemu-system-x86_64 -M q35 -m 512M -serial stdio -cdrom $(ISO)

# -s = GDB-Server auf :1234, -S = CPU startet angehalten
debug: $(ISO)
	qemu-system-x86_64 $(QEMU_FLAGS) -s -S

clean:
	cd kernel && cargo clean
	rm -rf build

distclean: clean
	rm -rf $(LIMINE)
