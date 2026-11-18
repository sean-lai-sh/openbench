#!/usr/bin/env node
// Extract the loaded memory image of an ELF binary as 32-bit words.
// Usage: node extract.js /path/to/a.out > out.json
'use strict';
const fs = require('fs');

const path = process.argv[2] || '/app/a.out';
const buf = fs.readFileSync(path);

if (buf.readUInt32BE(0) !== 0x7f454c46) {
  console.error('Not an ELF file');
  process.exit(1);
}
const is64 = buf[4] === 2;
const le = buf[5] === 1;

const u16 = (o) => (le ? buf.readUInt16LE(o) : buf.readUInt16BE(o));
const u32 = (o) => (le ? buf.readUInt32LE(o) : buf.readUInt32BE(o));
const u64 = (o) => Number(le ? buf.readBigUInt64LE(o) : buf.readBigUInt64BE(o));
const addr = (o) => (is64 ? u64(o) : u32(o));

const phoff = is64 ? u64(0x20) : u32(0x1c);
const phentsize = u16(is64 ? 0x36 : 0x2a);
const phnum = u16(is64 ? 0x38 : 0x2c);
const shoff = is64 ? u64(0x28) : u32(0x20);
const shentsize = u16(is64 ? 0x3a : 0x2e);
const shnum = u16(is64 ? 0x3c : 0x30);

// Collect regions [vaddr, fileOffset, size] of file-backed memory.
const regions = [];
for (let i = 0; i < phnum; i++) {
  const p = phoff + i * phentsize;
  const type = u32(p);
  if (type !== 1) continue; // PT_LOAD
  let offset, vaddr, filesz;
  if (is64) {
    offset = u64(p + 8);
    vaddr = u64(p + 16);
    filesz = u64(p + 32);
  } else {
    offset = u32(p + 4);
    vaddr = u32(p + 8);
    filesz = u32(p + 16);
  }
  regions.push([vaddr, offset, filesz]);
}

// Fallback: use allocated, file-backed sections if there are no segments.
if (regions.length === 0 && shoff) {
  for (let i = 0; i < shnum; i++) {
    const s = shoff + i * shentsize;
    const type = u32(s + 4);
    const flags = is64 ? u64(s + 8) : u32(s + 8);
    const saddr = addr(s + (is64 ? 16 : 12));
    const off = is64 ? u64(s + 24) : u32(s + 16);
    const size = is64 ? u64(s + 32) : u32(s + 20);
    if (type === 8 || !(flags & 2) || size === 0) continue; // skip NOBITS / non-alloc
    regions.push([saddr, off, size]);
  }
}

const out = {};
for (const [vaddr, offset, size] of regions) {
  // Emit 4-byte aligned words that lie fully within the file-backed region.
  let a = Math.ceil(vaddr / 4) * 4;
  for (; a + 4 <= vaddr + size; a += 4) {
    const o = offset + (a - vaddr);
    if (o + 4 > buf.length) break;
    out[a] = u32(o);
  }
}

process.stdout.write(JSON.stringify(out) + '\n');
