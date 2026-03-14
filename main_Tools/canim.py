# ===== canim.py =====
# Shank 2 .canim Parser v10 — Extract/Rebuild JSON support

import struct, sys, os, math, time, json

class C:
    H='\033[95m';B='\033[94m';C='\033[96m';G='\033[92m'
    Y='\033[93m';R='\033[91m';E='\033[0m';BOLD='\033[1m'

# ── Read helpers ──
def r8(d,p):
    if p+1>len(d): raise ValueError(f"EOF@0x{p:04X}")
    return d[p],p+1
def r16(d,p):
    if p+2>len(d): raise ValueError(f"EOF@0x{p:04X}")
    return struct.unpack_from('<H',d,p)[0],p+2
def r32(d,p):
    if p+4>len(d): raise ValueError(f"EOF@0x{p:04X}")
    return struct.unpack_from('<I',d,p)[0],p+4
def rf(d,p):
    if p+4>len(d): raise ValueError(f"EOF@0x{p:04X}")
    return struct.unpack_from('<f',d,p)[0],p+4
def rstr(d,p):
    l,p2=r32(d,p)
    if l>500: raise ValueError(f"String len={l}@0x{p2:04X}")
    if p2+l>len(d): raise ValueError(f"EOF str[{l}]@0x{p2:04X}")
    return d[p2:p2+l].decode('ascii',errors='replace'),p2+l

# ── Write helpers ──
def w8(buf,v):
    buf.append(v&0xFF)
def w16(buf,v):
    buf.extend(struct.pack('<H',v))
def w32(buf,v):
    buf.extend(struct.pack('<I',v))
def wf(buf,v):
    buf.extend(struct.pack('<f',v))
def wstr(buf,s):
    enc=s.encode('ascii')
    w32(buf,len(enc))
    buf.extend(enc)

# ── Validation helpers ──
def valid_str(d,p):
    if p+4>len(d): return False
    l=struct.unpack_from('<I',d,p)[0]
    if l==0 or l>300 or p+4+l>len(d): return False
    return all(32<=d[p+4+i]<127 for i in range(l))

def empty_str_at(d,p):
    if p+4>len(d): return False
    return struct.unpack_from('<I',d,p)[0]==0

def is_float_reasonable(v):
    if math.isnan(v) or math.isinf(v): return False
    return -10000.0<=v<=10000.0

def hexdump(d,o,n,pfx="    "):
    e=min(o+n,len(d))
    for i in range(o,e,16):
        h="";a=""
        for j in range(16):
            if i+j<e:
                b=d[i+j]; h+=f"{b:02X} "; a+=chr(b) if 32<=b<127 else '.'
            else: h+="   "
        print(f"{pfx}{i:08X} | {h}| {a}")

def try_parse_sprite(d, pos, fs):
    try:
        if pos+4>fs: return None
        spf,p=r16(d,pos); spu,p=r16(d,p)
        if empty_str_at(d,p):
            p+=4
            if p+16>fs: return None
            sw,p=rf(d,p); sh,p=rf(d,p); spx,p=rf(d,p); spy,p=rf(d,p)
            return({'frame':spf,'unk':spu,'name':'',
                    'width':sw,'height':sh,'pivot_x':spx,'pivot_y':spy,'empty':True},p)
        if not valid_str(d,p): return None
        spn,p=rstr(d,p)
        if p+16>fs: return None
        sw,p=rf(d,p); sh,p=rf(d,p); spx,p=rf(d,p); spy,p=rf(d,p)
        if not(is_float_reasonable(sw) and is_float_reasonable(sh)
               and is_float_reasonable(spx) and is_float_reasonable(spy)):
            return None
        if sw<0 or sh<0 or sw>5000 or sh>5000: return None
        return({'frame':spf,'unk':spu,'name':spn,
                'width':sw,'height':sh,'pivot_x':spx,'pivot_y':spy,'empty':False},p)
    except(ValueError,IndexError):
        return None

def try_parse_bare_sprite(d, pos, fs):
    try:
        if not valid_str(d,pos): return None
        spn,p=rstr(d,pos)
        if p+16>fs: return None
        sw,p=rf(d,p); sh,p=rf(d,p); spx,p=rf(d,p); spy,p=rf(d,p)
        if not(is_float_reasonable(sw) and is_float_reasonable(sh)
               and is_float_reasonable(spx) and is_float_reasonable(spy)):
            return None
        if sw<0 or sh<0 or sw>5000 or sh>5000: return None
        return({'frame':0,'unk':0,'name':spn,
                'width':sw,'height':sh,'pivot_x':spx,'pivot_y':spy,'empty':False},p)
    except(ValueError,IndexError):
        return None

KNOWN_RATES={1,2,3,4,5,6,8,10,12,15,20,24,25,30,60}

def is_symbol_header(d,pos,fs):
    if not valid_str(d,pos): return False
    try:
        name,p=rstr(d,pos)
        if p+3>fs: return False
        rate=d[p]; count=struct.unpack_from('<H',d,p+1)[0]
        if rate not in KNOWN_RATES: return False
        if count>5000: return False
        if '/' in name: return False
        return True
    except(ValueError,IndexError):
        return False

def find_next_symbol(d,pos,fs):
    scan=pos
    while scan<fs-7:
        if is_symbol_header(d,scan,fs): return scan
        scan+=1
    return fs

def looks_like_section(d,pos,fs,layers):
    if not valid_str(d,pos): return False
    try:
        name,p=rstr(d,pos)
        if p+9>fs: return False
        p+=4; sf=d[p]; p+=1
        sfc=struct.unpack_from('<H',d,p)[0]; p+=2
        sec=struct.unpack_from('<H',d,p)[0]; p+=2
        if sfc>10000 or sec>10000: return False
        if sfc==0 and sec==0: return False
        if sec>0 and p+6<=fs:
            li=struct.unpack_from('<H',d,p+4)[0]
            if li>=len(layers) and li>100: return False
        return True
    except(ValueError,IndexError):
        return False

def looks_like_build(d,pos,fs):
    if not valid_str(d,pos): return False
    try:
        name,p=rstr(d,pos)
        if 'Slot0/' in name or 'GRP_' in name: return True
        if p+3<=fs and d[p] in KNOWN_RATES: return True
        return False
    except(ValueError,IndexError):
        return False

def detect_minimal_format(d, pos, fs):
    if not valid_str(d,pos): return False
    try:
        name,p=rstr(d,pos)
        if '-' not in name: return False
        if p+16>fs: return False
        sw=struct.unpack_from('<f',d,p)[0]
        sh=struct.unpack_from('<f',d,p+4)[0]
        return sw>0 and sw<5000 and sh>0 and sh<5000
    except(ValueError,IndexError):
        return False


def parse_nested_symbol(d, pos, fs, sym_name, rate, count, verbose):
    sym={'name':sym_name,'frame_rate':rate,'num_sprites':0,'sprites':[],
         'composite':True,'sub_symbols':[],'_timeline_size':0}
    start_pos=pos; sub_names=[]
    while valid_str(d,pos):
        if is_symbol_header(d,pos,fs):
            try:
                tn,tp=rstr(d,pos); tr=d[tp]; tc=struct.unpack_from('<H',d,tp+1)[0]
                if tr in KNOWN_RATES and tc<5000:
                    tp2=tp+3
                    if try_parse_sprite(d,tp2,fs) is not None: break
                    if valid_str(d,tp2) and len(sub_names)>=count: break
            except(ValueError,IndexError): pass
        try:
            sn2,pos=rstr(d,pos); sub_names.append(sn2)
            if len(sub_names)>=count and count>0: break
        except ValueError: break
    sym['sub_symbols']=sub_names
    if verbose:
        print(f"    {C.Y}[composite] {len(sub_names)} sub-symbols{C.E}")
        for i,sn2 in enumerate(sub_names):
            if i<8: print(f"      sub[{i}]: \"{C.C}{sn2}{C.E}\"")
            elif i==8: print(f"      ... ({len(sub_names)-8} more)")
    next_sym=find_next_symbol(d,pos,fs)
    sym['_timeline_size']=next_sym-start_pos
    if verbose: print(f"    {C.B}[block size] {next_sym-start_pos} bytes{C.E}")
    return sym, next_sym


def parse_build_section(d, pos, fs, layers, verbose):
    symbols=[]; tsp=0; build_secs=[]; build_entries=[]
    build_start=pos

    while pos<fs-4:
        if not valid_str(d,pos) and not empty_str_at(d,pos): break
        sst=pos

        if is_symbol_header(d,pos,fs):
            entry_start=pos
            try:
                sn,pos=rstr(d,pos); sr,pos=r8(d,pos); snsp,pos=r16(d,pos)
            except ValueError: pos=sst; break

            if verbose:
                print(f"\n  Symbol: \"{C.Y}{sn}{C.E}\" rate={sr} count={snsp}")

            if snsp==0:
                sym={'name':sn,'frame_rate':sr,'num_sprites':0,'sprites':[],
                     'composite':False,'sub_symbols':[],'_timeline_size':0}
                next_sym=find_next_symbol(d,pos,fs)
                if next_sym>pos:
                    tl_size=next_sym-pos
                    if pos+4<=fs:
                        pc=struct.unpack_from('<H',d,pos)[0]
                        pu=struct.unpack_from('<H',d,pos+2)[0]
                        if 0<pc<200 and pos+4<next_sym:
                            tp=pos+4; sn_list=[]
                            for _ in range(pc):
                                if valid_str(d,tp):
                                    tn,tp=rstr(d,tp); sn_list.append(tn)
                                else: break
                            if len(sn_list)==pc:
                                sym['composite']=True; sym['sub_symbols']=sn_list
                                sym['_timeline_size']=tl_size
                                if verbose:
                                    print(f"    {C.Y}[nested] {pc} sub-items{C.E}")
                                    for i,s in enumerate(sn_list[:5]):
                                        print(f"      sub[{i}]: \"{C.C}{s}{C.E}\"")
                                    print(f"    {C.B}[block] {tl_size}B{C.E}")
                                sym['_raw_hex']=d[entry_start:next_sym].hex()
                                sym['_entry_type']='symbol'
                                pos=next_sym; symbols.append(sym)
                                build_entries.append(sym)
                                continue
                    sym['_timeline_size']=tl_size
                    if verbose: print(f"    {C.B}[timeline] {tl_size}B{C.E}")
                    pos=next_sym
                sym['_raw_hex']=d[entry_start:pos].hex()
                sym['_entry_type']='symbol'
                symbols.append(sym); build_entries.append(sym)
                continue

            test=try_parse_sprite(d,pos,fs)
            if test is not None:
                sym={'name':sn,'frame_rate':sr,'num_sprites':snsp,'sprites':[],
                     'composite':False,'sub_symbols':[]}
                if verbose: print(f"    [simple] {snsp} sprites")
                sok=True
                for si in range(snsp):
                    result=try_parse_sprite(d,pos,fs)
                    if result is None:
                        if verbose:
                            print(f"  {C.R}[!] Sprite {si}/{snsp} @0x{pos:04X}{C.E}")
                            hexdump(d,pos,min(64,fs-pos))
                        sok=False; break
                    sprite,pos=result; sym['sprites'].append(sprite)
                    if verbose:
                        if sprite.get('empty'):
                            if si<3 or si==snsp-1:
                                print(f"    [{si:>3}] fr={sprite['frame']:<3} (empty)")
                        elif si<3 or si==snsp-1:
                            print(f"    [{si:>3}] fr={sprite['frame']:<3} "
                                  f"\"{C.C}{sprite['name']}{C.E}\" "
                                  f"({sprite['width']:.0f}x{sprite['height']:.0f})")
                        elif si==3 and snsp>4:
                            print(f"    ... ({snsp-4} more)")
                tsp+=len(sym['sprites'])
                sym['_raw_hex']=d[entry_start:pos].hex()
                sym['_entry_type']='symbol'
                symbols.append(sym); build_entries.append(sym)
                if not sok: break
            elif valid_str(d,pos):
                sym,pos=parse_nested_symbol(d,pos,fs,sn,sr,snsp,verbose)
                sym['_raw_hex']=d[entry_start:pos].hex()
                sym['_entry_type']='symbol'
                symbols.append(sym); build_entries.append(sym)
            else:
                if verbose:
                    print(f"    {C.Y}[nested binary] @0x{pos:04X}{C.E}")
                    hexdump(d,pos,min(48,fs-pos))
                sym={'name':sn,'frame_rate':sr,'num_sprites':snsp,'sprites':[],
                     'composite':True,'sub_symbols':[],'_timeline_size':0}
                next_sym=find_next_symbol(d,pos,fs)
                sym['_timeline_size']=next_sym-pos
                if verbose: print(f"    {C.B}[block] {next_sym-pos}B{C.E}")
                sym['_raw_hex']=d[entry_start:next_sym].hex()
                sym['_entry_type']='symbol'
                pos=next_sym; symbols.append(sym); build_entries.append(sym)
        else:
            entry_start=pos
            try: sn,tpos=rstr(d,pos)
            except ValueError: break
            if verbose: print(f"\n  {C.B}[BUILD timeline] \"{sn}\" @0x{pos:04X}{C.E}")
            next_sym=find_next_symbol(d,pos+1,fs)
            tl_size=next_sym-pos
            bsec={'name':sn,'_data_size':tl_size,'_start':pos,
                  '_raw_hex':d[entry_start:next_sym].hex(),'_entry_type':'build_section'}
            build_secs.append(bsec); build_entries.append(bsec)
            if verbose:
                print(f"    {C.B}[block] {tl_size}B{C.E}")
            pos=next_sym

    return symbols,tsp,build_secs,pos,build_entries


def _empty_result(magic='????',version=0,hf1=0,hf2=0,anim_name='',
                  frame_rate=0,fs=0,skipped=False):
    return {
        'magic':magic,'version':version,'hf1':hf1,'hf2':hf2,
        'anim_name':anim_name,'frame_rate':frame_rate,
        'num_clips':0,'num_sections':0,'total_elements':0,
        'layers':[],'clips':[],'sections':[],'symbols':[],
        'build_sections':[],'build_entries':[],'filesize':fs,
        '_trail':0,'_trail_hex':'','_tel':0,
        '_has_traditional_sections':False,'_minimal':False,
        '_skipped':skipped,'_unk2':0,'_minimal_meta_hex':''
    }


def parse_canim(filepath, verbose=True):
    with open(filepath,'rb') as f:
        data=bytearray(f.read())
    fn=os.path.basename(filepath)
    fs=len(data); pos=0

    if fs<20:
        if verbose:
            print(f"\n  {C.R}[SKIP] \"{fn}\" too small ({fs} bytes){C.E}\n")
        return _empty_result(fs=fs,skipped=True)

    if verbose:
        print(f"\n{C.BOLD}{C.H}")
        print(f"╔═══════════════════════════════════════════════════╗")
        print(f"║   Shank 2 .canim Parser v10                      ║")
        print(f"║   {fn:<47} ║")
        print(f"╚═══════════════════════════════════════════════════╝{C.E}\n")

    magic=data[0:4].decode('ascii'); pos=4
    version,pos=r32(data,pos)
    hf1,pos=r16(data,pos); hf2,pos=r16(data,pos)
    if verbose:
        print(f"{C.BOLD}[HEADER]{C.E}  {magic} v{version}  f1={hf1} f2={hf2}  size={fs}")

    anim_name,pos=rstr(data,pos)
    if verbose:
        print(f"{C.BOLD}[ANIM]{C.E}   \"{C.C}{anim_name}{C.E}\"")

    meta_start=pos
    if verbose:
        print(f"\n{C.BOLD}[METADATA] @0x{pos:04X}{C.E}")
        print(f"  Bytes: {data[pos:pos+11].hex().upper()}")

    m_rate,pos=r8(data,pos)

    # ── MINIMAL FORMAT (hf1==0) ──
    if hf1==0:
        scan=pos
        sprite_start=None
        while scan<fs-4:
            if valid_str(data,scan):
                try:
                    tn,_=rstr(data,scan)
                    if '-' in tn:
                        sprite_start=scan; break
                except ValueError: pass
            scan+=1

        if sprite_start is not None:
            minimal_meta_hex=data[pos:sprite_start].hex()
            if verbose:
                print(f"  {C.Y}[MINIMAL FORMAT]{C.E} f1=0")
                print(f"  Meta: {minimal_meta_hex.upper()}")

            pos=sprite_start
            sprites=[]
            while pos<fs-4:
                result=try_parse_bare_sprite(data,pos,fs)
                if result is None: break
                sprite,pos=result; sprites.append(sprite)

            symbols=[{'name':anim_name,'frame_rate':m_rate,
                       'num_sprites':len(sprites),'sprites':sprites,
                       'composite':False,'sub_symbols':[]}]
            trail=fs-pos
            trail_hex=data[pos:].hex() if trail>0 else ''

            if verbose:
                print(f"\n  Symbol: \"{C.Y}{anim_name}{C.E}\" sprites={len(sprites)}")
                for i,sp in enumerate(sprites):
                    if i<5 or i==len(sprites)-1:
                        print(f"    [{i}] \"{C.C}{sp['name']}{C.E}\" ({sp['width']:.0f}x{sp['height']:.0f})")
                if trail==0: print(f"\n  {C.G}Parsed completely! ✓{C.E}")
                else: print(f"\n  {C.R}Trailing: {trail}B @0x{pos:04X}{C.E}")
                print(f"\n{'='*65}")
                print(f"{C.BOLD}  SUMMARY{C.E}")
                print(f"{'='*65}")
                print(f"  Anim:     \"{anim_name}\"  rate={m_rate}fps")
                print(f"  Format:   MINIMAL")
                print(f"  Sprites:  {len(sprites)}")
                print(f"  Trailing: {trail} {'✓' if trail==0 else '✗'}")
                print(f"{'='*65}\n")

            return {
                'magic':magic,'version':version,'hf1':hf1,'hf2':hf2,
                'anim_name':anim_name,'frame_rate':m_rate,
                'num_clips':0,'num_sections':0,'total_elements':0,
                'layers':[],'clips':[],'sections':[],'symbols':symbols,
                'build_sections':[],'build_entries':[],'filesize':fs,
                '_trail':trail,'_trail_hex':trail_hex,'_tel':0,
                '_has_traditional_sections':False,'_minimal':True,
                '_unk2':0,'_minimal_meta_hex':minimal_meta_hex
            }

    # ── NORMAL FORMAT ──
    m_clips,pos=r16(data,pos)
    m_sections,pos=r16(data,pos)
    m_elements,pos=r16(data,pos)
    m_unk2,pos=r16(data,pos)
    m_layers,pos=r16(data,pos)

    if verbose:
        print(f"  Rate={m_rate}fps  Clips={m_clips}  Sections={m_sections}  "
              f"Elements={m_elements}  Unk2={m_unk2}  Layers={m_layers}")

    # ── LAYERS ──
    if verbose: print(f"\n{C.BOLD}[LAYERS] @0x{pos:04X}{C.E}  ({m_layers})")
    layers=[]
    for i in range(m_layers):
        if not valid_str(data,pos):
            if verbose:
                print(f"  {C.R}[!] Bad layer @0x{pos:04X}{C.E}")
                hexdump(data,pos,32)
            break
        nm,pos=rstr(data,pos); layers.append(nm)
        if verbose: print(f"  [{i:>2}] \"{C.G}{nm}{C.E}\"")

    # ── CLIPS ──
    clips=[]
    if m_clips>0:
        if verbose:
            print(f"\n{C.BOLD}[ANIM CLIPS] @0x{pos:04X}{C.E}  ({m_clips})")
        for i in range(m_clips):
            if not valid_str(data,pos):
                if verbose: print(f"  {C.R}[!] Bad clip @0x{pos:04X}{C.E}")
                break
            try:
                cn,pos=rstr(data,pos); cv,pos=r16(data,pos)
                clips.append({'name':cn,'value':cv})
                if verbose:
                    print(f"  [{i:>2}] \"{C.Y}{cn}{C.E}\"  value={cv}")
            except ValueError as ex:
                if verbose: print(f"  {C.R}[!] Clip {i}: {ex}{C.E}")
                break

    # ── SECTIONS ──
    has_trad_sec=looks_like_section(data,pos,fs,layers)
    is_build=looks_like_build(data,pos,fs) if not has_trad_sec else False

    if verbose and not has_trad_sec and is_build:
        print(f"\n  {C.Y}[NOTE] No traditional sections — BUILD format{C.E}")

    sections=[]; tel=0
    if has_trad_sec:
        if verbose:
            print(f"\n{C.BOLD}[SECTIONS] @0x{pos:04X}{C.E}  ({m_sections})")
        for si in range(m_sections):
            if not looks_like_section(data,pos,fs,layers):
                if verbose: print(f"  {C.Y}[!] Section {si} end @0x{pos:04X}{C.E}")
                break
            ss=pos
            try:
                fn_,pos=rstr(data,pos)
                su,pos=r32(data,pos); sf,pos=r8(data,pos)
                sfc,pos=r16(data,pos); sec,pos=r16(data,pos)
            except ValueError:
                pos=ss; break
            if sec>10000 or sfc>10000: pos=ss; break
            s={'name':fn_,'unknown':su,'facing':sf,
               'frame_count':sfc,'element_count':sec,'elements':[]}
            if verbose:
                print(f"  [{si:>2}] \"{C.C}{fn_}{C.E}\" fr={sfc} el={sec}")
            ok=True
            for ei in range(sec):
                es=pos
                try:
                    idx,pos=r16(data,pos); u1,pos=r16(data,pos)
                    li,pos=r16(data,pos); u2,pos=r16(data,pos)
                    ma,pos=rf(data,pos); md,pos=rf(data,pos)
                    mb,pos=rf(data,pos); mc,pos=rf(data,pos)
                    tx,pos=rf(data,pos); ty,pos=rf(data,pos)
                    zo,pos=r16(data,pos); tp,pos=r8(data,pos)
                    cr,pos=r8(data,pos); cg,pos=r8(data,pos)
                    cb,pos=r8(data,pos); ca,pos=r8(data,pos)
                    pd=data[pos:pos+4]; pos+=4
                except(ValueError,IndexError) as ex:
                    if verbose: print(f"  {C.R}[!] Elem {ei}/{sec} @0x{es:04X}: {ex}{C.E}")
                    ok=False; break
                ln=layers[li] if li<len(layers) else f"?{li}"
                s['elements'].append({
                    'index':idx,'unk1':u1,'layer_idx':li,'layer_name':ln,
                    'unk2':u2,'matrix':(ma,mb,mc,md),'tx':tx,'ty':ty,
                    'z_ord':zo,'type':tp,'color':(cr,cg,cb,ca),'pad':pd.hex()
                })
            tel+=len(s['elements']); sections.append(s)
            if not ok: break
        if verbose:
            em='✓' if tel==m_elements else '✗'
            print(f"\n  Elements: {tel}/{m_elements} {em}")

    # ── BUILD ──
    brem=fs-pos
    if verbose:
        print(f"\n{C.BOLD}[BUILD] @0x{pos:04X}{C.E}  ({brem} bytes)")
        if brem>0:
            print(f"  First 128 bytes:")
            hexdump(data,pos,min(128,brem))

    symbols,tsp,build_secs,pos,build_entries=parse_build_section(data,pos,fs,layers,verbose)

    trail=fs-pos
    trail_hex=data[pos:].hex() if trail>0 else ''

    if verbose:
        if trail==0: print(f"\n  {C.G}Parsed completely! ✓{C.E}")
        elif trail>0:
            print(f"\n  {C.R}Trailing: {trail}B @0x{pos:04X}{C.E}")
            if trail<=256: hexdump(data,pos,trail)

    if verbose:
        print(f"\n{'='*65}")
        print(f"{C.BOLD}  SUMMARY{C.E}")
        print(f"{'='*65}")
        print(f"  Anim:     \"{anim_name}\"  rate={m_rate}fps")
        print(f"  Header:   f1={hf1} f2={hf2}")
        print(f"  Layers:   {len(layers)} (meta={m_layers})")
        print(f"  Clips:    {len(clips)} (meta={m_clips})")
        if clips:
            for cl in clips: print(f"            \"{cl['name']}\" val={cl['value']}")
        if has_trad_sec:
            em='✓' if tel==m_elements else '✗'
            print(f"  Sections: {len(sections)}/{m_sections} ({tel}/{m_elements} el) {em}")
        else:
            print(f"  Sections: {C.Y}embedded in BUILD{C.E} (meta={m_sections}, {m_elements} el)")
        total_sym=len(symbols)
        comp_count=sum(1 for s in symbols if s.get('composite'))
        if build_secs: print(f"  Build TL: {len(build_secs)} blocks")
        if comp_count>0:
            sm=f'{total_sym} ({total_sym-comp_count} simple, {comp_count} composite)'
        else:
            sm=f'{total_sym} ✓' if total_sym==len(layers) else f'{total_sym} ✗'
        print(f"  Symbols:  {sm}  Sprites: {tsp}")
        print(f"  Trailing: {trail} {'✓' if trail==0 else '✗'}")
        if symbols:
            for sy in symbols:
                sp=sy['sprites']; real=[s for s in sp if not s.get('empty')]
                emp=len(sp)-len(real)
                fr=sorted(set(s['frame'] for s in real)) if real else []
                fs_=f"{min(fr)}-{max(fr)}" if fr else "none"
                ct=" [C]" if sy.get('composite') else ""
                subs=sy.get('sub_symbols',[])
                si=f" subs={len(subs)}" if subs else ""
                tl=sy.get('_timeline_size',0)
                ti=f" tl={tl}B" if tl>0 else ""
                ei=f" ({emp} empty)" if emp>0 else ""
                print(f"    \"{sy['name']:<20}\" spr={len(sp):<4} fr={fs_}{ei}{ct}{si}{ti}")
        print(f"{'='*65}\n")

    return {
        'magic':magic,'version':version,'hf1':hf1,'hf2':hf2,
        'anim_name':anim_name,'frame_rate':m_rate,
        'num_clips':m_clips,'num_sections':m_sections,
        'total_elements':m_elements,
        'layers':layers,'clips':clips,
        'sections':sections,'symbols':symbols,
        'build_sections':build_secs,'build_entries':build_entries,
        'filesize':fs,'_trail':trail,'_trail_hex':trail_hex,'_tel':tel,
        '_has_traditional_sections':has_trad_sec,'_minimal':False,
        '_unk2':m_unk2,'_minimal_meta_hex':''
    }


# ══════════════════════════════════════════════════════════════
#  EXPORT: canim -> JSON
# ══════════════════════════════════════════════════════════════

def export_canim_to_json(canim_path, json_path=None):
    """Parse a .canim and write its full structure to JSON."""
    result = parse_canim(canim_path, verbose=False)
    if result.get('_skipped'):
        raise ValueError(f"File too small or invalid: {canim_path}")

    if json_path is None:
        json_path = canim_path + '.json'

    out = {
        '_format': 'canim_v10',
        'magic': result['magic'],
        'version': result['version'],
        'hf1': result['hf1'],
        'hf2': result['hf2'],
        'anim_name': result['anim_name'],
        'frame_rate': result['frame_rate'],
        '_minimal': result.get('_minimal', False),
        '_minimal_meta_hex': result.get('_minimal_meta_hex', ''),
        '_has_traditional_sections': result.get('_has_traditional_sections', False),
        '_unk2': result.get('_unk2', 0),
        'num_clips': result['num_clips'],
        'num_sections': result['num_sections'],
        'total_elements': result['total_elements'],
    }

    # Layers
    out['layers'] = result.get('layers', [])

    # Clips
    out['clips'] = result.get('clips', [])

    # Sections
    json_sections = []
    for sec in result.get('sections', []):
        js = {
            'name': sec['name'],
            'unknown': sec['unknown'],
            'facing': sec['facing'],
            'frame_count': sec['frame_count'],
            'element_count': sec['element_count'],
            'elements': []
        }
        for el in sec.get('elements', []):
            je = {
                'index': el['index'],
                'unk1': el['unk1'],
                'layer_idx': el['layer_idx'],
                'layer_name': el['layer_name'],
                'unk2': el['unk2'],
                'matrix': list(el['matrix']),
                'tx': el['tx'],
                'ty': el['ty'],
                'z_ord': el['z_ord'],
                'type': el['type'],
                'color': list(el['color']),
                'pad': el['pad']
            }
            js['elements'].append(je)
        json_sections.append(js)
    out['sections'] = json_sections

    # Build entries (ordered)
    json_build = []
    for entry in result.get('build_entries', []):
        je = {'_entry_type': entry.get('_entry_type', 'symbol')}
        je['_raw_hex'] = entry.get('_raw_hex', '')

        if entry.get('_entry_type') == 'build_section':
            je['name'] = entry.get('name', '')
            je['_data_size'] = entry.get('_data_size', 0)
        else:
            je['name'] = entry.get('name', '')
            je['frame_rate'] = entry.get('frame_rate', 0)
            je['num_sprites'] = entry.get('num_sprites', 0)
            je['composite'] = entry.get('composite', False)
            je['sub_symbols'] = entry.get('sub_symbols', [])
            je['_timeline_size'] = entry.get('_timeline_size', 0)
            sprites_out = []
            for sp in entry.get('sprites', []):
                sprites_out.append({
                    'frame': sp['frame'],
                    'unk': sp['unk'],
                    'name': sp['name'],
                    'width': sp['width'],
                    'height': sp['height'],
                    'pivot_x': sp['pivot_x'],
                    'pivot_y': sp['pivot_y'],
                    'empty': sp.get('empty', False)
                })
            je['sprites'] = sprites_out
        json_build.append(je)
    out['build_entries'] = json_build

    # Minimal format sprites (flat list for easy editing)
    if result.get('_minimal'):
        min_sprites = []
        for sym in result.get('symbols', []):
            for sp in sym.get('sprites', []):
                min_sprites.append({
                    'name': sp['name'],
                    'width': sp['width'],
                    'height': sp['height'],
                    'pivot_x': sp['pivot_x'],
                    'pivot_y': sp['pivot_y']
                })
        out['minimal_sprites'] = min_sprites

    out['_trail_hex'] = result.get('_trail_hex', '')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    return json_path


# ══════════════════════════════════════════════════════════════
#  REBUILD: JSON -> canim
# ══════════════════════════════════════════════════════════════

def _write_symbol_from_parsed(buf, sym):
    """Reconstruct a simple (non-composite) symbol from parsed fields."""
    wstr(buf, sym['name'])
    w8(buf, sym['frame_rate'])
    w16(buf, sym.get('num_sprites', len(sym.get('sprites', []))))
    for sp in sym.get('sprites', []):
        w16(buf, sp.get('frame', 0))
        w16(buf, sp.get('unk', 0))
        name = sp.get('name', '')
        if sp.get('empty', False) or name == '':
            w32(buf, 0)  # empty string length = 0
        else:
            wstr(buf, name)
        wf(buf, sp['width'])
        wf(buf, sp['height'])
        wf(buf, sp['pivot_x'])
        wf(buf, sp['pivot_y'])


def rebuild_canim_from_json(json_path, canim_path=None):
    """Rebuild a .canim binary from a JSON export."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data.get('_format') != 'canim_v10':
        raise ValueError("JSON is not a canim_v10 export")

    if canim_path is None:
        if json_path.endswith('.canim.json'):
            canim_path = json_path[:-5]  # remove .json
        else:
            canim_path = json_path.rsplit('.', 1)[0] + '.canim'

    buf = bytearray()

    # ── HEADER ──
    buf.extend(data['magic'].encode('ascii'))
    w32(buf, data['version'])
    w16(buf, data['hf1'])
    w16(buf, data['hf2'])
    wstr(buf, data['anim_name'])

    # ── METADATA ──
    w8(buf, data['frame_rate'])

    is_minimal = data.get('_minimal', False)

    if is_minimal:
        # Write minimal metadata hex
        meta_hex = data.get('_minimal_meta_hex', '')
        if meta_hex:
            buf.extend(bytes.fromhex(meta_hex))

        # Write bare sprites
        for sp in data.get('minimal_sprites', []):
            wstr(buf, sp['name'])
            wf(buf, sp['width'])
            wf(buf, sp['height'])
            wf(buf, sp['pivot_x'])
            wf(buf, sp['pivot_y'])

        # Trailing
        trail_hex = data.get('_trail_hex', '')
        if trail_hex:
            buf.extend(bytes.fromhex(trail_hex))

        with open(canim_path, 'wb') as f:
            f.write(buf)
        return canim_path

    # ── NORMAL FORMAT ──
    w16(buf, data['num_clips'])
    w16(buf, data['num_sections'])
    w16(buf, data['total_elements'])
    w16(buf, data.get('_unk2', 0))
    w16(buf, len(data.get('layers', [])))

    # ── LAYERS ──
    for layer in data.get('layers', []):
        wstr(buf, layer)

    # ── CLIPS ──
    for clip in data.get('clips', []):
        wstr(buf, clip['name'])
        w16(buf, clip['value'])

    # ── SECTIONS ──
    if data.get('_has_traditional_sections', False):
        for sec in data.get('sections', []):
            wstr(buf, sec['name'])
            w32(buf, sec['unknown'])
            w8(buf, sec['facing'])
            w16(buf, sec['frame_count'])
            w16(buf, sec['element_count'])
            for el in sec.get('elements', []):
                w16(buf, el['index'])
                w16(buf, el['unk1'])
                w16(buf, el['layer_idx'])
                w16(buf, el['unk2'])
                # matrix stored as (ma, mb, mc, md) but file order is ma, md, mb, mc
                mx = el['matrix']
                wf(buf, mx[0])  # ma
                wf(buf, mx[3])  # md
                wf(buf, mx[1])  # mb
                wf(buf, mx[2])  # mc
                wf(buf, el['tx'])
                wf(buf, el['ty'])
                w16(buf, el['z_ord'])
                w8(buf, el['type'])
                color = el['color']
                w8(buf, color[0])
                w8(buf, color[1])
                w8(buf, color[2])
                w8(buf, color[3])
                buf.extend(bytes.fromhex(el['pad']))

    # ── BUILD ENTRIES ──
    for entry in data.get('build_entries', []):
        raw_hex = entry.get('_raw_hex', '')
        if raw_hex:
            # Use raw hex for perfect reconstruction
            buf.extend(bytes.fromhex(raw_hex))
        else:
            # Fallback: reconstruct from parsed data (simple symbols only)
            if entry.get('_entry_type') == 'symbol' and not entry.get('composite', False):
                _write_symbol_from_parsed(buf, entry)
            # composite/build_section without raw_hex: can't reconstruct
            # (this shouldn't happen if JSON was generated by export)

    # ── TRAILING ──
    trail_hex = data.get('_trail_hex', '')
    if trail_hex:
        buf.extend(bytes.fromhex(trail_hex))

    with open(canim_path, 'wb') as f:
        f.write(buf)
    return canim_path


# ══════════════════════════════════════════════════════════════
#  BATCH OPERATIONS
# ══════════════════════════════════════════════════════════════

def batch_export(folder, verbose=True):
    """Export all .canim files in a folder to .canim.json"""
    files = sorted(f for f in os.listdir(folder)
                   if f.endswith('.canim') and '.canim-meta' not in f)
    success = 0; errors = 0
    for fn in files:
        fp = os.path.join(folder, fn)
        try:
            out = export_canim_to_json(fp)
            if verbose: print(f"  [OK] {fn} -> {os.path.basename(out)}")
            success += 1
        except Exception as e:
            if verbose: print(f"  [ERR] {fn}: {e}")
            errors += 1
    if verbose:
        print(f"\n  Done: {success} exported, {errors} errors out of {len(files)}")
    return success, errors, len(files)


def batch_rebuild(folder, verbose=True):
    """Rebuild all .canim.json files in a folder back to .canim"""
    files = sorted(f for f in os.listdir(folder) if f.endswith('.canim.json'))
    success = 0; errors = 0
    for fn in files:
        fp = os.path.join(folder, fn)
        try:
            out = rebuild_canim_from_json(fp)
            if verbose: print(f"  [OK] {fn} -> {os.path.basename(out)}")
            success += 1
        except Exception as e:
            if verbose: print(f"  [ERR] {fn}: {e}")
            errors += 1
    if verbose:
        print(f"\n  Done: {success} rebuilt, {errors} errors out of {len(files)}")
    return success, errors, len(files)


# ══════════════════════════════════════════════════════════════
#  VERIFY: roundtrip check
# ══════════════════════════════════════════════════════════════

def verify_roundtrip(canim_path, verbose=True):
    """Export then rebuild and compare binary output to original."""
    import tempfile
    with open(canim_path, 'rb') as f:
        original = f.read()

    tmp_json = tempfile.mktemp(suffix='.canim.json')
    tmp_canim = tempfile.mktemp(suffix='.canim')

    try:
        export_canim_to_json(canim_path, tmp_json)
        rebuild_canim_from_json(tmp_json, tmp_canim)
        with open(tmp_canim, 'rb') as f:
            rebuilt = f.read()

        if original == rebuilt:
            if verbose: print(f"  ✓ {os.path.basename(canim_path)}: PERFECT match ({len(original)} bytes)")
            return True
        else:
            if verbose:
                print(f"  ✗ {os.path.basename(canim_path)}: MISMATCH "
                      f"(orig={len(original)} rebuilt={len(rebuilt)})")
                # Find first difference
                for i in range(min(len(original), len(rebuilt))):
                    if original[i] != rebuilt[i]:
                        print(f"    First diff at offset 0x{i:04X}: "
                              f"orig=0x{original[i]:02X} rebuilt=0x{rebuilt[i]:02X}")
                        break
            return False
    finally:
        for p in [tmp_json, tmp_canim]:
            try: os.unlink(p)
            except: pass


def batch_verify(folder, verbose=True):
    """Verify roundtrip for all .canim files in folder."""
    files = sorted(f for f in os.listdir(folder)
                   if f.endswith('.canim') and '.canim-meta' not in f)
    ok = 0; fail = 0
    for fn in files:
        fp = os.path.join(folder, fn)
        try:
            if verify_roundtrip(fp, verbose):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            if verbose: print(f"  ✗ {fn}: ERROR {e}")
            fail += 1
    if verbose:
        print(f"\n  Roundtrip: {ok}/{len(files)} perfect, {fail} mismatches")
    return ok, fail


# ══════════════════════════════════════════════════════════════
#  BATCH REPORT (unchanged from v9)
# ══════════════════════════════════════════════════════════════

def batch_report(results):
    ok=[r for r in results if r.get('_trail',1)==0
        and(r.get('_tel',0)==r.get('total_elements',1)
            or not r.get('_has_traditional_sections',True)
            or r.get('_minimal',False)
            or r.get('_skipped',False))]
    warn=[r for r in results if r not in ok and r.get('_error') is None]
    err=[r for r in results if r.get('_error') is not None]

    tsp=sum(sum(len(s['sprites']) for s in r.get('symbols',[])) for r in results if '_error' not in r)
    tsym=sum(len(r.get('symbols',[])) for r in results if '_error' not in r)

    print(f"\n{C.BOLD}{C.H}")
    print(f"╔═══════════════════════════════════════════════════════════════════╗")
    print(f"║                    BATCH ANALYSIS REPORT                         ║")
    print(f"╚═══════════════════════════════════════════════════════════════════╝{C.E}")
    print(f"\n{C.BOLD}  FILES: {len(results)}{C.E}  "
          f"{C.G}✓{len(ok)}{C.E}  {C.Y}⚠{len(warn)}{C.E}  {C.R}✗{len(err)}{C.E}")
    print(f"  Symbols: {tsym}  Sprites: {tsp}")

    print(f"\n  {'FILE':<42} {'SIZE':>8} {'LAY':>4} {'SYM':>4} {'SPR':>5} STATUS")
    print(f"  {'─'*42} {'─'*8} {'─'*4} {'─'*4} {'─'*5} {'─'*12}")
    for r in results:
        fn=r.get('_filename','?')
        if '_error' in r:
            print(f"  {fn:<42} {C.R}ERROR: {r['_error']}{C.E}"); continue
        fsize=r.get('filesize',0); nl=len(r.get('layers',[])); trail=r.get('_trail',0)
        nsym=len(r.get('symbols',[])); nsp=sum(len(s['sprites']) for s in r.get('symbols',[]))
        if r.get('_skipped'):
            st=f"{C.Y}⊘ SKIP ({fsize}B){C.E}"
        elif r.get('_minimal'):
            st=f"{C.G}✓ MIN{C.E}"
        elif trail==0:
            st=f"{C.G}✓{C.E}"
        else:
            st=f"{C.Y}⚠ t={trail}{C.E}"
        print(f"  {fn:<42} {fsize:>8} {nl:>4} {nsym:>4} {nsp:>5} {st}")

    prob=[r for r in results if r.get('_trail',0)>0 and not r.get('_skipped',False)]
    if prob:
        print(f"\n{C.Y}  ISSUES:{C.E}")
        for r in prob: print(f"    {r.get('_filename','?')}: trail={r['_trail']}B")
    print(f"\n{'='*70}\n")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

if __name__=='__main__':
    if len(sys.argv)<2:
        print(f"\n  Usage:")
        print(f"    python {os.path.basename(__file__)} <file.canim>           # analyze")
        print(f"    python {os.path.basename(__file__)} --batch <folder>       # batch analyze (verbose)")
        print(f"    python {os.path.basename(__file__)} --all <folder>         # batch analyze (summary)")
        print(f"    python {os.path.basename(__file__)} --export <file.canim>  # export to JSON")
        print(f"    python {os.path.basename(__file__)} --export-all <folder>  # export all to JSON")
        print(f"    python {os.path.basename(__file__)} --rebuild <file.json>  # rebuild from JSON")
        print(f"    python {os.path.basename(__file__)} --rebuild-all <folder> # rebuild all from JSON")
        print(f"    python {os.path.basename(__file__)} --verify <file.canim>  # verify roundtrip")
        print(f"    python {os.path.basename(__file__)} --verify-all <folder>  # verify all roundtrips\n")
        sys.exit(1)

    mode=sys.argv[1]

    # ── Export single ──
    if mode=='--export' and len(sys.argv)>=3:
        fp=sys.argv[2]
        try:
            out=export_canim_to_json(fp)
            print(f"  [OK] Exported: {out}")
        except Exception as e:
            print(f"  [ERR] {e}")
        sys.exit(0)

    # ── Export all ──
    if mode=='--export-all' and len(sys.argv)>=3:
        batch_export(sys.argv[2])
        sys.exit(0)

    # ── Rebuild single ──
    if mode=='--rebuild' and len(sys.argv)>=3:
        fp=sys.argv[2]
        try:
            out=rebuild_canim_from_json(fp)
            print(f"  [OK] Rebuilt: {out}")
        except Exception as e:
            print(f"  [ERR] {e}")
        sys.exit(0)

    # ── Rebuild all ──
    if mode=='--rebuild-all' and len(sys.argv)>=3:
        batch_rebuild(sys.argv[2])
        sys.exit(0)

    # ── Verify single ──
    if mode=='--verify' and len(sys.argv)>=3:
        verify_roundtrip(sys.argv[2])
        sys.exit(0)

    # ── Verify all ──
    if mode=='--verify-all' and len(sys.argv)>=3:
        batch_verify(sys.argv[2])
        sys.exit(0)

    # ── Batch / Summary / All ──
    if mode in('--batch','--summary','--all') and len(sys.argv)>=3:
        folder=sys.argv[2]
        files=sorted(f for f in os.listdir(folder)
                     if f.endswith('.canim') and '.canim-meta' not in f)
        verb=(mode=='--batch')

        if mode=='--all':
            print(f"\n  Found {len(files)} .canim files\n")
            for fn in files:
                fp=os.path.join(folder,fn)
                try:
                    r=parse_canim(fp,verbose=False)
                    if r.get('_skipped'):
                        print(f"  {fn:<38} SKIP ({r['filesize']}B)")
                        continue
                    t=r['_trail']; ns=len(r['symbols'])
                    sp=sum(len(s['sprites']) for s in r['symbols'])
                    nl=len(r.get('layers',[]))
                    st='✓' if t==0 else f'trail={t}'
                    mi=' MIN' if r.get('_minimal') else ''
                    print(f"  {fn:<38} lay={nl:<3} sym={ns:>2} spr={sp:>4} {st}{mi}")
                except Exception as ex:
                    print(f"  {fn:<38} ERROR: {ex}")
            sys.exit(0)

        print(f"\n  {C.BOLD}Found {len(files)} .canim files in {folder}{C.E}\n")
        if verb: print(f"  {'='*65}")
        results=[]; t0=time.time()
        for i,fn in enumerate(files):
            fp=os.path.join(folder,fn)
            if verb:
                print(f"\n  {C.BOLD}[{i+1}/{len(files)}] {fn}{C.E}")
                print(f"  {'-'*65}")
            try:
                r=parse_canim(fp,verbose=verb); r['_filename']=fn; results.append(r)
            except Exception as ex:
                if verb: print(f"  {C.R}FATAL: {ex}{C.E}")
                results.append({'_filename':fn,'_error':str(ex),
                    '_trail':0,'_tel':0,'total_elements':0,
                    'symbols':[],'sections':[],'layers':[],
                    'clips':[],'num_sections':0,'filesize':0,'frame_rate':0})
        print(f"\n  {C.BOLD}Done in {time.time()-t0:.2f}s{C.E}")
        batch_report(results); sys.exit(0)

    # ── Single / Multi file analyze ──
    targets=[]
    for arg in sys.argv[1:]:
        if os.path.isfile(arg): targets.append(arg)
        elif os.path.isdir(arg):
            for fn in sorted(os.listdir(arg)):
                if fn.endswith('.canim') and '.canim-meta' not in fn:
                    targets.append(os.path.join(arg,fn))
        else: print(f"  {C.R}Not found: {arg}{C.E}")
    if not targets: print(f"  {C.R}No .canim files{C.E}"); sys.exit(1)

    if len(targets)==1:
        parse_canim(targets[0])
    else:
        results=[]
        for i,fp in enumerate(targets):
            fn=os.path.basename(fp)
            print(f"\n  {C.BOLD}[{i+1}/{len(targets)}] {fn}{C.E}")
            print(f"  {'-'*65}")
            try:
                r=parse_canim(fp); r['_filename']=fn; results.append(r)
            except Exception as ex:
                print(f"  {C.R}FATAL: {ex}{C.E}")
                results.append({'_filename':fn,'_error':str(ex),
                    '_trail':0,'_tel':0,'total_elements':0,
                    'symbols':[],'sections':[],'layers':[],
                    'clips':[],'num_sections':0,'filesize':0,'frame_rate':0})
        if len(results)>1: batch_report(results)