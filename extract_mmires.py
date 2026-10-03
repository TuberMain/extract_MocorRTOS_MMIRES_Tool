import os
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def extract_mmires(mmires_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    
    with open(mmires_path, 'rb') as f:
        data = f.read()
    
    print(f"文件大小: {len(data)} bytes")
    sections = []
    
    # 查找所有 section header
    for magic_str in [b'sres0001', b'tres0001']:
        pos = 0
        while True:
            idx = data.find(magic_str, pos)
            if idx == -1:
                break
            count = struct.unpack_from('<I', data, idx + 8)[0]
            data_off = struct.unpack_from('<I', data, idx + 0x10)[0]
            sections.append({
                'magic': magic_str.decode(),
                'base': idx,
                'count': count,
                'data_offset': data_off
            })
            pos = idx + 8
    
    print(f"\n找到 {len(sections)} 个资源段:")
    for s in sections:
        print(f"  {s['magic']} @ 0x{s['base']:08x}, {s['count']} 条目, data_off=0x{s['data_offset']:08x}")
    print("\n--- SRES 命名资源 ---")
    sres_base = 0
    sres_entry_start = sres_base + 0x110  # 资源条目从 0x110 开始
    
    for i in range(16):
        pos = sres_entry_start + i * 12
        name_bytes = data[pos:pos+4]
        name = name_bytes.decode('ascii', errors='replace').rstrip('\x00')
        res_off = struct.unpack_from('<I', data, pos + 4)[0]
        res_sz = struct.unpack_from('<I', data, pos + 8)[0]
        
        if res_sz == 0 or res_off >= len(data) or res_off + res_sz > len(data):
            continue
        
        res_data = data[res_off:res_off + res_sz]
        ext = identify_type(res_data)
        safe_name = sanitize(name) if name else f"res_{i:02d}"
        fname = f"sres_{safe_name}{ext}"
        
        with open(os.path.join(out_dir, fname), 'wb') as f:
            f.write(res_data)
        print(f"  {fname} ({res_sz} bytes)")
    print("\n--- 嵌入文件批量提取 ---")
    
    extractors = [
        ('png', b'\x89PNG\r\n\x1a\n', b'IEND\xaeB`\x82'),
        ('gif', b'GIF89a', b'\x00;'),
        ('gif', b'GIF87a', b'\x00;'),
        ('jpg', b'\xff\xd8\xff', b'\xff\xd9'),
        ('wav', b'RIFF', None),  # 使用 RIFF header 中的大小
    ]
    
    subdir = os.path.join(out_dir, 'embedded')
    os.makedirs(subdir, exist_ok=True)
    
    total = 0
    for fmt, start_sig, end_sig in extractors:
        pos = 0
        count = 0
        while True:
            idx = data.find(start_sig, pos)
            if idx == -1:
                break
            
            if end_sig:
                end = data.find(end_sig, idx + len(start_sig))
                if end == -1:
                    break
                end += len(end_sig)
            elif fmt == 'wav':
                riff_size = struct.unpack_from('<I', data, idx + 4)[0]
                end = idx + riff_size + 8
                if end > len(data):
                    break
            else:
                break
            
            res = data[idx:end]
            
            # 最小大小过滤 (跳过太小的碎片)
            if len(res) < 32:
                pos = idx + 1
                continue
            
            fname = f"{fmt}_{count:04d}.{fmt}"
            with open(os.path.join(subdir, fname), 'wb') as f:
                f.write(res)
            
            count += 1
            pos = end
        
        if count > 0:
            print(f"  {fmt.upper()}: {count} 个文件")
            total += count
    
    print(f"\n总计提取: {total} 个嵌入文件")
    print("\n--- 字符串/文本资源 ---")
    text_dir = os.path.join(out_dir, 'strings')
    os.makedirs(text_dir, exist_ok=True)
    
    # 从 TRES 段提取
    for s in sections:
        if s['magic'] == 'tres0001':
            extract_tres_strings(data, s, text_dir)
    
    print(f"\n完成! 所有文件已输出到: {out_dir}")

def extract_tres_strings(data, section, out_dir):
    """提取 TRES 段的字符串资源"""
    base = section['base']
    count = section['count']
    
    # TRES 资源条目从 base+0x14 开始, 每条 12 字节
    entry_start = base + 0x14
    
    # 偏移表在条目之后
    offset_table = entry_start + count * 12
    
    offsets = []
    for i in range(count + 1):
        pos = offset_table + i * 4
        if pos + 4 <= len(data):
            offsets.append(struct.unpack_from('<I', data, pos)[0])
    
    for i in range(min(count, len(offsets) - 1)):
        off = offsets[i]
        sz = offsets[i+1] - offsets[i]
        
        if off >= len(data) or off + sz > len(data) or sz <= 0:
            continue
        
        res_data = data[off:off+sz]
        
        # 检查是否为文本
        sample = res_data[:min(256, len(res_data))]
        printable = sum(1 for b in sample if 32 <= b < 127 or b in (10, 13, 9, 0))
        if printable > len(sample) * 0.7:
            fname = f"tres_string_{i:03d}.txt"
            with open(os.path.join(out_dir, fname), 'wb') as f:
                f.write(res_data)
            preview = res_data[:80].decode('ascii', errors='replace')
            print(f"  {fname} ({sz} bytes): {preview[:60]}...")

def identify_type(d):
    if d[:8] == b'\x89PNG\r\n\x1a\n': return '.png'
    if d[:3] == b'GIF': return '.gif'
    if d[:2] == b'\xff\xd8': return '.jpg'
    if d[:2] == b'BM': return '.bmp'
    if d[:4] == b'RIFF': return '.wav'
    if d[:4] == b'PK\x03\x04': return '.zip'
    return '.bin'

def sanitize(name):
    return ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)

if __name__ == '__main__':
    if len(sys.argv) >= 3:
        mmires_path = sys.argv[1]
        out_dir = sys.argv[2]
        extract_mmires(mmires_path, out_dir)
    else:
        print("Usage: python extract_mmires.py <MMIRES file path> <output directory>")
        sys.exit(1)