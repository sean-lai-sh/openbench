#!/usr/bin/env node
// Extracts the initial memory image of an ELF binary as 32-bit words.
// Usage: node extract.js /app/a.out > out.json
//
// The memory image is built the way a loader would: the file-backed bytes of
// every PT_LOAD segment are placed at their virtual address. Bytes of
// allocated (SHF_ALLOC, non-NOBITS) sections are also added (they normally
// coincide with segment contents). Words are emitted at every 4-byte aligned
// address, plus at 4-byte steps relative to each section start (in case a
// section starts unaligned). Only words whose 4 bytes are all backed by file
// data are emitted; values are unsigned 32-bit integers in the ELF's byte order.

const fs = require('fs');

function main() {
  const path = process.argv[2];
  if (!path) {
    process.stderr.write('usage: node extract.js <elf-file>\n');
    process.exit(1);
  }
  const buf = fs.readFileSync(path);
  if (buf.length < 16 || buf.readUInt32BE(0) !== 0x7f454c46) {
    process.stderr.write('not an ELF file\n');
    process.exit(1);
  }

  const is64 = buf[4] === 2;
  const le = buf[5] !== 2;

  const u16 = (o) => (le ? buf.readUInt16LE(o) : buf.readUInt16BE(o));
  const u32 = (o) => (le ? buf.readUInt32LE(o) : buf.readUInt32BE(o));
  const uaddr = (o) =>
    is64 ? Number(le ? buf.readBigUInt64LE(o) : buf.readBigUInt64BE(o)) : u32(o);

  let phoff, shoff, phentsize, phnum, shentsize, shnum;
  if (is64) {
    phoff = uaddr(0x20);
    shoff = uaddr(0x28);
    phentsize = u16(0x36);
    phnum = u16(0x38);
    shentsize = u16(0x3a);
    shnum = u16(0x3c);
  } else {
    phoff = u32(0x1c);
    shoff = u32(0x20);
    phentsize = u16(0x2a);
    phnum = u16(0x2c);
    shentsize = u16(0x2e);
    shnum = u16(0x30);
  }

  const mem = new Map(); // address -> byte
  const put = (addr, off, size) => {
    for (let i = 0; i < size; i++) {
      if (off + i >= buf.length) break;
      mem.set(addr + i, buf[off + i]);
    }
  };

  // Program headers (PT_LOAD = 1)
  for (let i = 0; i < phnum; i++) {
    const o = phoff + i * phentsize;
    if (o + phentsize > buf.length) break;
    const type = u32(o);
    if (type !== 1) continue;
    let off, vaddr, filesz;
    if (is64) {
      off = uaddr(o + 8);
      vaddr = uaddr(o + 16);
      filesz = uaddr(o + 32);
    } else {
      off = u32(o + 4);
      vaddr = u32(o + 8);
      filesz = u32(o + 16);
    }
    put(vaddr, off, filesz);
  }

  // Section headers: allocated, file-backed sections
  const sectionStarts = [];
  for (let i = 0; i < shnum; i++) {
    const o = shoff + i * shentsize;
    if (o + shentsize > buf.length) break;
    const type = u32(o + 4);
    let flags, addr, off, size;
    if (is64) {
      flags = uaddr(o + 8);
      addr = uaddr(o + 16);
      off = uaddr(o + 24);
      size = uaddr(o + 32);
    } else {
      flags = u32(o + 8);
      addr = u32(o + 12);
      off = u32(o + 16);
      size = u32(o + 20);
    }
    const SHT_NOBITS = 8, SHF_ALLOC = 2;
    if (type === 0 || type === SHT_NOBITS || !(flags & SHF_ALLOC) || size === 0) continue;
    put(addr, off, size);
    sectionStarts.push([addr, size]);
  }

  const word = (a) => {
    const b0 = mem.get(a), b1 = mem.get(a + 1), b2 = mem.get(a + 2), b3 = mem.get(a + 3);
    if (b0 === undefined || b1 === undefined || b2 === undefined || b3 === undefined) return undefined;
    const v = le
      ? (b0 | (b1 << 8) | (b2 << 16) | (b3 << 24))
      : ((b0 << 24) | (b1 << 16) | (b2 << 8) | b3);
    return v >>> 0;
  };

  const out = new Map();
  for (const a of mem.keys()) {
    if (a % 4 !== 0) continue;
    const v = word(a);
    if (v !== undefined) out.set(a, v);
  }
  for (const [addr, size] of sectionStarts) {
    for (let i = 0; i + 4 <= size; i += 4) {
      const v = word(addr + i);
      if (v !== undefined) out.set(addr + i, v);
    }
  }

  const keys = [...out.keys()].sort((x, y) => x - y);
  const parts = keys.map((k) => JSON.stringify(String(k)) + ': ' + out.get(k));
  process.stdout.write('{' + parts.join(', ') + '}\n');
}

main();
