import struct
import sys
import os


class LuaParser:
    """Custom Lua table parser"""
    
    def __init__(self, code):
        self.code = code
        self.pos = 0
        self.length = len(code)
    
    def skip_whitespace(self):
        while self.pos < self.length:
            if self.code[self.pos] in ' \t\n\r':
                self.pos += 1
            elif self.code[self.pos:self.pos+2] == '--':
                while self.pos < self.length and self.code[self.pos] != '\n':
                    self.pos += 1
            else:
                break
    
    def peek(self):
        self.skip_whitespace()
        if self.pos < self.length:
            return self.code[self.pos]
        return None
    
    def consume(self, expected=None):
        self.skip_whitespace()
        if expected:
            if self.code[self.pos:self.pos+len(expected)] == expected:
                self.pos += len(expected)
                return expected
            raise ValueError(f"Expected '{expected}' at position {self.pos}")
        char = self.code[self.pos]
        self.pos += 1
        return char
    
    def parse_string(self):
        self.skip_whitespace()
        quote = self.code[self.pos]
        if quote not in '"\'':
            raise ValueError(f"Expected string at position {self.pos}")
        
        self.pos += 1
        result = []
        
        while self.pos < self.length:
            char = self.code[self.pos]
            
            if char == quote:
                self.pos += 1
                return ''.join(result)
            elif char == '\\':
                self.pos += 1
                if self.pos < self.length:
                    next_char = self.code[self.pos]
                    escape_map = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"', "'": "'"}
                    result.append(escape_map.get(next_char, next_char))
                    self.pos += 1
            else:
                result.append(char)
                self.pos += 1
        
        raise ValueError("Unterminated string")
    
    def parse_number(self):
        self.skip_whitespace()
        start = self.pos
        
        if self.pos < self.length and self.code[self.pos] == '-':
            self.pos += 1
        
        while self.pos < self.length and (self.code[self.pos].isdigit() or self.code[self.pos] == '.'):
            self.pos += 1
        
        if self.pos < self.length and self.code[self.pos] in 'eE':
            self.pos += 1
            if self.pos < self.length and self.code[self.pos] in '+-':
                self.pos += 1
            while self.pos < self.length and self.code[self.pos].isdigit():
                self.pos += 1
        
        num_str = self.code[start:self.pos]
        
        if '.' in num_str or 'e' in num_str.lower():
            return float(num_str)
        return int(num_str)
    
    def parse_identifier(self):
        self.skip_whitespace()
        start = self.pos
        
        while self.pos < self.length:
            char = self.code[self.pos]
            if char.isalnum() or char == '_':
                self.pos += 1
            else:
                break
        
        return self.code[start:self.pos]
    
    def parse_value(self):
        self.skip_whitespace()
        
        if self.pos >= self.length:
            return None
        
        char = self.peek()
        
        if char in '"\'':
            return self.parse_string()
        
        if char == '{':
            return self.parse_table()
        
        if char == '-' or char.isdigit():
            if char == '-':
                if self.pos + 1 < self.length and self.code[self.pos + 1].isdigit():
                    return self.parse_number()
            else:
                return self.parse_number()
        
        if char.isalpha() or char == '_':
            ident = self.parse_identifier()
            if ident == 'true':
                return True
            elif ident == 'false':
                return False
            elif ident == 'nil':
                return None
            return ident
        
        raise ValueError(f"Unexpected character '{char}' at position {self.pos}")
    
    def parse_table(self):
        self.consume('{')
        result = {}
        array_index = 1
        
        while True:
            self.skip_whitespace()
            
            if self.peek() == '}':
                self.consume('}')
                break
            
            if self.peek() == '[':
                self.consume('[')
                key = self.parse_value()
                self.consume(']')
                self.skip_whitespace()
                self.consume('=')
                value = self.parse_value()
                result[key] = value
            else:
                saved_pos = self.pos
                
                if self.peek() and (self.peek().isalpha() or self.peek() == '_'):
                    ident = self.parse_identifier()
                    self.skip_whitespace()
                    
                    if self.peek() == '=':
                        self.consume('=')
                        value = self.parse_value()
                        result[ident] = value
                    else:
                        self.pos = saved_pos
                        value = self.parse_value()
                        result[array_index] = value
                        array_index += 1
                else:
                    value = self.parse_value()
                    result[array_index] = value
                    array_index += 1
            
            self.skip_whitespace()
            if self.peek() == ',':
                self.consume(',')
        
        if result and all(isinstance(k, int) for k in result.keys()):
            max_idx = max(result.keys())
            if set(result.keys()) == set(range(1, max_idx + 1)):
                return [result[i] for i in range(1, max_idx + 1)]
        
        return result
    
    def parse_assignment(self):
        self.skip_whitespace()
        name = self.parse_identifier()
        self.skip_whitespace()
        self.consume('=')
        value = self.parse_value()
        return name, value


def parse_lua_file(filepath):
    """Read and parse Lua file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    lines = []
    for line in code.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        lines.append(line)
    
    clean_code = '\n'.join(lines).strip()
    
    parser = LuaParser(clean_code)
    return parser.parse_assignment()


class LuaCompiler:
    """Compile Lua table to Bytecode 5.1"""
    
    OP_LOADK = 1
    OP_LOADBOOL = 2
    OP_LOADNIL = 3
    OP_SETGLOBAL = 7
    OP_SETTABLE = 9
    OP_NEWTABLE = 10
    OP_SETLIST = 34
    OP_RETURN = 30
    
    def __init__(self):
        self.output = bytearray()
        self.constants = []
        self.const_map = {}
        self.instructions = []
        self.max_stack = 2
    
    def write_byte(self, b):
        self.output.append(b & 0xFF)
    
    def write_int(self, val):
        self.output.extend(struct.pack('<i', val))
    
    def write_size_t(self, val):
        self.output.extend(struct.pack('<I', val))
    
    def write_number(self, val):
        self.output.extend(struct.pack('<d', float(val)))
    
    def write_string(self, s):
        if s is None:
            self.write_size_t(0)
        else:
            encoded = s.encode('latin-1', errors='replace') + b'\x00'
            self.write_size_t(len(encoded))
            self.output.extend(encoded)
    
    def write_instruction(self, opcode, a=0, b=0, c=0, bx=None):
        if bx is not None:
            inst = (opcode & 0x3F) | ((a & 0xFF) << 6) | ((bx & 0x3FFFF) << 14)
        else:
            inst = (opcode & 0x3F) | ((a & 0xFF) << 6) | ((c & 0x1FF) << 14) | ((b & 0x1FF) << 23)
        self.output.extend(struct.pack('<I', inst))
    
    def write_header(self):
        self.output.extend(b'\x1bLua')
        self.write_byte(0x51)
        self.write_byte(0x00)
        self.write_byte(0x01)
        self.write_byte(0x04)
        self.write_byte(0x04)
        self.write_byte(0x04)
        self.write_byte(0x08)
        self.write_byte(0x00)
    
    def add_constant(self, val):
        if isinstance(val, int) and not isinstance(val, bool):
            val = float(val)
        
        key = (type(val).__name__, str(val))
        if key in self.const_map:
            return self.const_map[key]
        
        idx = len(self.constants)
        self.constants.append(val)
        self.const_map[key] = idx
        return idx
    
    def rk(self, idx):
        return idx + 256 if idx < 256 else idx
    
    def emit(self, opcode, a=0, b=0, c=0, bx=None):
        self.instructions.append((opcode, a, b, c, bx))
        if a + 1 > self.max_stack:
            self.max_stack = a + 1
    
    def compile_value(self, val, reg):
        if val is None:
            self.emit(self.OP_LOADNIL, reg, reg)
        elif isinstance(val, bool):
            self.emit(self.OP_LOADBOOL, reg, 1 if val else 0, 0)
        elif isinstance(val, (int, float)):
            idx = self.add_constant(val)
            self.emit(self.OP_LOADK, reg, bx=idx)
        elif isinstance(val, str):
            idx = self.add_constant(val)
            self.emit(self.OP_LOADK, reg, bx=idx)
        elif isinstance(val, list):
            self.compile_list(val, reg)
        elif isinstance(val, dict):
            self.compile_dict(val, reg)
        
        return reg
    
    def compile_list(self, lst, reg):
        self.emit(self.OP_NEWTABLE, reg, len(lst), 0)
        
        if not lst:
            return reg
        
        for i, item in enumerate(lst):
            item_reg = reg + 1 + i
            self.compile_value(item, item_reg)
            if item_reg + 1 > self.max_stack:
                self.max_stack = item_reg + 2
        
        self.emit(self.OP_SETLIST, reg, len(lst), 1)
        return reg
    
    def compile_dict(self, dct, reg):
        hash_size = len(dct)
        hash_log = 0
        while (1 << hash_log) < hash_size:
            hash_log += 1
        
        self.emit(self.OP_NEWTABLE, reg, 0, hash_log)
        
        for key, val in dct.items():
            key_idx = self.rk(self.add_constant(key))
            
            if isinstance(val, (list, dict)):
                val_reg = reg + 1
                self.compile_value(val, val_reg)
                if val_reg + 1 > self.max_stack:
                    self.max_stack = val_reg + 2
                self.emit(self.OP_SETTABLE, reg, key_idx, val_reg)
            elif val is None:
                val_reg = reg + 1
                self.emit(self.OP_LOADNIL, val_reg, val_reg)
                self.emit(self.OP_SETTABLE, reg, key_idx, val_reg)
            elif isinstance(val, bool):
                val_idx = self.rk(self.add_constant(val))
                self.emit(self.OP_SETTABLE, reg, key_idx, val_idx)
            else:
                val_idx = self.rk(self.add_constant(val))
                self.emit(self.OP_SETTABLE, reg, key_idx, val_idx)
        
        return reg
    
    def compile_table(self, global_name, table):
        self.compile_value(table, 0)
        name_idx = self.add_constant(global_name)
        self.emit(self.OP_SETGLOBAL, 0, bx=name_idx)
        self.emit(self.OP_RETURN, 0, 1)
    
    def build_bytecode(self):
        self.output = bytearray()
        self.write_header()
        
        self.write_string(None)
        self.write_int(0)
        self.write_int(0)
        self.write_byte(0)
        self.write_byte(0)
        self.write_byte(2)
        self.write_byte(self.max_stack + 10)
        
        self.write_int(len(self.instructions))
        for opcode, a, b, c, bx in self.instructions:
            self.write_instruction(opcode, a, b, c, bx=bx)
        
        self.write_int(len(self.constants))
        for const in self.constants:
            if const is None:
                self.write_byte(0)
            elif isinstance(const, bool):
                self.write_byte(1)
                self.write_byte(1 if const else 0)
            elif isinstance(const, float):
                self.write_byte(3)
                self.write_number(const)
            elif isinstance(const, str):
                self.write_byte(4)
                self.write_string(const)
        
        self.write_int(0)
        self.write_int(0)
        self.write_int(0)
        self.write_int(0)
        
        return bytes(self.output)


class LuaDecompiler:
    """Decompile Lua 5.1 Bytecode"""
    
    def __init__(self, data):
        self.data = data
        self.pos = 0
    
    def read_byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b
    
    def read_int(self):
        val = struct.unpack('<i', self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val
    
    def read_size_t(self):
        val = struct.unpack('<I', self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val
    
    def read_number(self):
        val = struct.unpack('<d', self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return val
    
    def read_string(self):
        size = self.read_size_t()
        if size == 0:
            return None
        s = self.data[self.pos:self.pos+size-1].decode('latin-1', errors='replace')
        self.pos += size
        return s
    
    def parse_header(self):
        self.pos = 12
    
    def parse_function(self):
        self.read_string()
        self.read_int()
        self.read_int()
        self.read_byte()
        self.read_byte()
        self.read_byte()
        self.read_byte()
        
        num_inst = self.read_int()
        instructions = []
        for _ in range(num_inst):
            instructions.append(struct.unpack('<I', self.data[self.pos:self.pos+4])[0])
            self.pos += 4
        
        num_const = self.read_int()
        constants = []
        for _ in range(num_const):
            t = self.read_byte()
            if t == 0:
                constants.append(None)
            elif t == 1:
                constants.append(self.read_byte() != 0)
            elif t == 3:
                constants.append(self.read_number())
            elif t == 4:
                constants.append(self.read_string())
        
        num_proto = self.read_int()
        for _ in range(num_proto):
            self.parse_function()
        
        num_lines = self.read_int()
        self.pos += num_lines * 4
        
        num_locals = self.read_int()
        for _ in range(num_locals):
            self.read_string()
            self.read_int()
            self.read_int()
        
        num_upval = self.read_int()
        for _ in range(num_upval):
            self.read_string()
        
        return instructions, constants
    
    def format_value(self, val, indent=0):
        prefix = "    " * indent
        
        if val is None:
            return "nil"
        elif isinstance(val, bool):
            return "true" if val else "false"
        elif isinstance(val, float):
            if val == int(val):
                return str(int(val))
            return str(val)
        elif isinstance(val, str):
            escaped = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            return f'"{escaped}"'
        elif isinstance(val, dict):
            if not val:
                return "{}"
            lines = ["{"]
            for k, v in val.items():
                fv = self.format_value(v, indent + 1)
                if isinstance(k, str) and k.isidentifier() and not k[0].isdigit():
                    lines.append(f"{prefix}    {k} = {fv},")
                else:
                    lines.append(f"{prefix}    [{self.format_value(k)}] = {fv},")
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        elif isinstance(val, list):
            if not val:
                return "{}"
            if all(isinstance(x, (int, float, str, bool, type(None))) for x in val):
                return "{ " + ", ".join(self.format_value(x) for x in val) + " }"
            lines = ["{"]
            for item in val:
                lines.append(f"{prefix}    {self.format_value(item, indent + 1)},")
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        return str(val)
    
    def reconstruct_table(self, instructions, constants):
        registers = {}
        global_name = None
        
        def get_const(idx):
            idx = idx - 256 if idx >= 256 else idx
            return constants[idx] if 0 <= idx < len(constants) else None
        
        for inst in instructions:
            opcode = inst & 0x3F
            a = (inst >> 6) & 0xFF
            b = (inst >> 23) & 0x1FF
            c = (inst >> 14) & 0x1FF
            bx = (inst >> 14) & 0x3FFFF
            
            if opcode == 10:
                registers[a] = {}
            elif opcode == 9:
                if a in registers and isinstance(registers[a], dict):
                    key = get_const(b) if b >= 256 else registers.get(b)
                    val = get_const(c) if c >= 256 else registers.get(c)
                    if key is not None:
                        registers[a][key] = val
            elif opcode == 1:
                registers[a] = get_const(bx)
            elif opcode == 34:
                if a in registers:
                    items = [registers.get(a + i + 1) for i in range(b)]
                    registers[a] = [x for x in items if x is not None] or registers[a]
            elif opcode == 7:
                global_name = get_const(bx)
        
        return global_name, registers.get(0, {})
    
    def decompile(self):
        self.parse_header()
        instructions, constants = self.parse_function()
        global_name, table = self.reconstruct_table(instructions, constants)
        
        if global_name:
            return f"{global_name} = {self.format_value(table)}\n"
        return f"return {self.format_value(table)}\n"


def compile_lua_file(input_path, output_path=None):
    """Compile Lua file to bytecode"""
    print(f"Compiling: {input_path}")
    
    global_name, table = parse_lua_file(input_path)
    
    print(f"  Global name: {global_name}")
    print(f"  Table type: {type(table).__name__}")
    
    compiler = LuaCompiler()
    compiler.compile_table(global_name, table)
    bytecode = compiler.build_bytecode()
    
    if output_path is None:
        output_path = input_path.rsplit('.', 1)[0] + '_compiled.lua'
    
    with open(output_path, 'wb') as f:
        f.write(bytecode)
    
    print(f"Done!")
    print(f"  Output: {output_path}")
    print(f"  Size: {len(bytecode)} bytes")
    print(f"  Constants: {len(compiler.constants)}")
    print(f"  Instructions: {len(compiler.instructions)}")
    
    return True


def decompile_file(input_path, output_path=None):
    """Decompile bytecode to Lua"""
    with open(input_path, 'rb') as f:
        data = f.read()
    
    if data[:4] != b'\x1bLua':
        print(f"Error: Not a Lua bytecode file")
        return False
    
    decompiler = LuaDecompiler(data)
    lua_code = decompiler.decompile()
    
    if output_path is None:
        output_path = input_path.rsplit('.', 1)[0] + '_decompiled.lua'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("-- Decompiled from Shank 2 Lua bytecode\n")
        f.write(f"-- Original file: {os.path.basename(input_path)}\n\n")
        f.write(lua_code)
    
    print(f"Decompiled: {input_path}")
    print(f"  Output: {output_path}")
    return True


def batch_decompile(folder_path, output_folder=None):
    """Decompile all bytecode files in folder"""
    if output_folder is None:
        output_folder = os.path.join(folder_path, "decompiled")
    
    os.makedirs(output_folder, exist_ok=True)
    
    success = 0
    failed = 0
    skipped = 0
    
    files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    
    print(f"Scanning {len(files)} files...")
    print("=" * 50)
    
    for filename in files:
        filepath = os.path.join(folder_path, filename)
        
        try:
            with open(filepath, 'rb') as f:
                header = f.read(4)
            
            if header == b'\x1bLua':
                out_name = os.path.splitext(filename)[0] + '_decompiled.lua'
                out_path = os.path.join(output_folder, out_name)
                
                with open(filepath, 'rb') as f:
                    data = f.read()
                
                decompiler = LuaDecompiler(data)
                lua_code = decompiler.decompile()
                
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(f"-- Decompiled from: {filename}\n\n")
                    f.write(lua_code)
                
                print(f"[OK] {filename}")
                success += 1
            else:
                skipped += 1
        
        except Exception as e:
            print(f"[FAIL] {filename}: {e}")
            failed += 1
    
    print("=" * 50)
    print(f"Done! Success: {success}, Failed: {failed}, Skipped: {skipped}")
    print(f"Output: {output_folder}")


def batch_compile(folder_path, output_folder=None):
    """Compile all Lua files in folder"""
    if output_folder is None:
        output_folder = os.path.join(folder_path, "compiled")
    
    os.makedirs(output_folder, exist_ok=True)
    
    success = 0
    failed = 0
    
    files = [f for f in os.listdir(folder_path) if f.endswith('.lua')]
    
    print(f"Compiling {len(files)} files...")
    print("=" * 50)
    
    for filename in files:
        filepath = os.path.join(folder_path, filename)
        
        try:
            with open(filepath, 'rb') as f:
                header = f.read(4)
            
            if header == b'\x1bLua':
                continue
            
            global_name, table = parse_lua_file(filepath)
            
            compiler = LuaCompiler()
            compiler.compile_table(global_name, table)
            bytecode = compiler.build_bytecode()
            
            out_name = filename.replace('_decompiled', '')
            out_path = os.path.join(output_folder, out_name)
            
            with open(out_path, 'wb') as f:
                f.write(bytecode)
            
            print(f"[OK] {filename} -> {out_name}")
            success += 1
        
        except Exception as e:
            print(f"[FAIL] {filename}: {e}")
            failed += 1
    
    print("=" * 50)
    print(f"Done! Success: {success}, Failed: {failed}")
    print(f"Output: {output_folder}")


def main():
    if len(sys.argv) < 2:
        print("=" * 50)
        print("  Shank 2 Lua Tool - Decompile & Compile")
        print("=" * 50)
        print("\nSingle file:")
        print("  python luaq_tool.py -d <file>           Decompile")
        print("  python luaq_tool.py -c <file>           Compile")
        print("  python luaq_tool.py -d <file> -o <out>  Custom output")
        print("  python luaq_tool.py -c <file> -o <out>  Custom output")
        print("\nBatch processing:")
        print("  python luaq_tool.py -db <folder>        Decompile all")
        print("  python luaq_tool.py -cb <folder>        Compile all")
        print("\nExamples:")
        print("  python luaq_tool.py -d boss_magnus.lua")
        print("  python luaq_tool.py -db C:\\game\\lua")
        print("  python luaq_tool.py -cb C:\\game\\lua\\decompiled")
        return
    
    mode = sys.argv[1]
    # the modes that you should type it in CMD
    if mode == '-d': # single file
        if len(sys.argv) >= 5 and sys.argv[3] == '-o': # -o give your file name before decode
            decompile_file(sys.argv[2], sys.argv[4])
        elif len(sys.argv) >= 3:
            decompile_file(sys.argv[2])
    
    elif mode == '-c': # for rebuild
        if len(sys.argv) >= 5 and sys.argv[3] == '-o': # -o give your file name before decode
            compile_lua_file(sys.argv[2], sys.argv[4])
        elif len(sys.argv) >= 3:
            compile_lua_file(sys.argv[2])
    
    elif mode == '-db': # decode all
        if len(sys.argv) >= 3:
            batch_decompile(sys.argv[2])
    
    elif mode == '-cb': # rebuild all
        if len(sys.argv) >= 3:
            batch_compile(sys.argv[2])
    
    else:
        print(f"Unknown mode: {mode}") # if you didn't type -d or -c or -db or -cd

        # ══════════════════════════════════════════════════════════════════════════════
#        GUI WRAPPER FUNCTIONS (for ShankTools UI)
# ══════════════════════════════════════════════════════════════════════════════

def luaq_decompile(input_file: str, output_file: str = "") -> str:
    """GUI-callable: Decompile Lua bytecode → Lua source"""
    try:
        out = output_file if output_file else None
        result = decompile_file(input_file, out)
        if result:
            out_name = output_file or (os.path.splitext(input_file)[0] + '_decompiled.lua')
            return f"✓ Decompiled: {os.path.basename(out_name)}"
        return "✗ Failed: Not a Lua bytecode file"
    except Exception as e:
        return f"✗ Failed: {e}"


def luaq_compile(input_file: str, output_file: str = "") -> str:
    """GUI-callable: Compile Lua source → bytecode"""
    try:
        out = output_file if output_file else None
        result = compile_lua_file(input_file, out)
        if result:
            out_name = output_file or (os.path.splitext(input_file)[0] + '_compiled.lua')
            return f"✓ Compiled: {os.path.basename(out_name)}"
        return "✗ Compilation failed"
    except Exception as e:
        return f"✗ Failed: {e}"


def luaq_info(input_file: str) -> str:
    """GUI-callable: Show Lua file info"""
    try:
        with open(input_file, 'rb') as f:
            data = f.read()

        file_size = len(data)
        basename = os.path.basename(input_file)

        if data[:4] == b'\x1bLua':
            version_byte = data[4] if len(data) > 4 else 0
            version_str = f"{version_byte >> 4}.{version_byte & 0x0F}"

            decompiler = LuaDecompiler(data)
            decompiler.parse_header()
            instructions, constants = decompiler.parse_function()
            global_name, table = decompiler.reconstruct_table(instructions, constants)

            num_strings = sum(1 for c in constants if isinstance(c, str))
            num_numbers = sum(1 for c in constants if isinstance(c, float))
            num_bools = sum(1 for c in constants if isinstance(c, bool))
            num_nils = sum(1 for c in constants if c is None)

            lines = [
                f"File: {basename}",
                f"Type: Lua Bytecode (compiled)",
                f"Lua Version: {version_str}",
                f"Size: {file_size:,} bytes",
                f"Global Name: {global_name or '(none)'}",
                f"Instructions: {len(instructions)}",
                f"Constants: {len(constants)} total",
                f"  Strings: {num_strings}",
                f"  Numbers: {num_numbers}",
                f"  Booleans: {num_bools}",
                f"  Nils: {num_nils}",
            ]

            if isinstance(table, dict):
                lines.append(f"Root Table: dict with {len(table)} key(s)")
            elif isinstance(table, list):
                lines.append(f"Root Table: array with {len(table)} element(s)")
            else:
                lines.append(f"Root Table: {type(table).__name__}")

            return "\n".join(lines)
        else:
            # Plain Lua source
            text = data.decode('utf-8', errors='replace')
            line_count = text.count('\n') + 1
            non_empty = sum(1 for l in text.split('\n') if l.strip())
            comment_lines = sum(1 for l in text.split('\n') if l.strip().startswith('--'))

            lines = [
                f"File: {basename}",
                f"Type: Lua Source (plain text)",
                f"Size: {file_size:,} bytes",
                f"Total Lines: {line_count}",
                f"Non-empty Lines: {non_empty}",
                f"Comment Lines: {comment_lines}",
            ]

            try:
                parser = LuaParser(text.strip())
                name = parser.parse_identifier()
                lines.append(f"Global Name: {name}")
            except Exception:
                pass

            return "\n".join(lines)

    except Exception as e:
        return f"✗ Failed to read file info: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#        register() — Called by main.py when loading from main_tools/
# ══════════════════════════════════════════════════════════════════════════════

def register(tool):
    """
    Registers a single LuaQ tool card.
    When clicked, it opens a full workspace panel with all features.
    """
    tool(
        icon="📜",
        title="LuaQ Converter",
        desc="Decompile & compile Shank 2 Lua 5.1 bytecode files",
        tool_info={
            "name": "LuaQ Converter",
            "icon": "📜",
            "custom_ui": True,
            "builder": build_luaq_panel,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
#                    EMBEDDED WORKSPACE UI
# ══════════════════════════════════════════════════════════════════════════════

def build_luaq_panel(parent, theme, status_cb, back_cb):
    """
    Builds the full LuaQ tool UI directly inside the workspace.
    Called by the app when the card is clicked.
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from pathlib import Path
    import threading

    # ── Main container ────────────────────────────────────────
    main = tk.Frame(parent, bg=theme["bg"])
    main.pack(fill="both", expand=True)

    # ── Top bar ───────────────────────────────────────────────
    top_bar = tk.Frame(main, bg=theme["bg_secondary"], height=50)
    top_bar.pack(fill="x")
    top_bar.pack_propagate(False)

    back_btn = tk.Button(
        top_bar, text="← Back", bg=theme["btn_bg"], fg=theme["btn_fg"],
        font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
        activebackground=theme["btn_hover"], command=back_cb,
    )
    back_btn.pack(side="left", padx=10, pady=8)

    tk.Label(
        top_bar, text="📜  LuaQ Converter",
        bg=theme["bg_secondary"], fg=theme["text"],
        font=("Segoe UI", 14, "bold"),
    ).pack(side="left", padx=10, pady=10)

    # ── Content area (two columns) ────────────────────────────
    content = tk.Frame(main, bg=theme["bg"])
    content.pack(fill="both", expand=True, padx=15, pady=10)

    # LEFT: File selection & options
    left_panel = tk.Frame(content, bg=theme["bg_panel"], width=400)
    left_panel.pack(side="left", fill="y", padx=(0, 8))
    left_panel.pack_propagate(False)

    # RIGHT: Output / log
    right_panel = tk.Frame(content, bg=theme["bg_panel"])
    right_panel.pack(side="left", fill="both", expand=True)

    # ══════════════════════════════════════════════════════════
    # LEFT PANEL
    # ══════════════════════════════════════════════════════════

    tk.Label(
        left_panel, text="Selected Files",
        bg=theme["bg_panel"], fg=theme["text"],
        font=("Segoe UI", 12, "bold"),
    ).pack(padx=12, pady=(12, 4), anchor="w")

    # ── File list ─────────────────────────────────────────────
    file_list_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    file_list_frame.pack(fill="both", expand=True, padx=12, pady=4)

    file_listbox = tk.Listbox(
        file_list_frame,
        bg=theme["entry_bg"], fg=theme["entry_fg"],
        selectbackground=theme["accent"],
        selectforeground="#FFFFFF",
        font=("Consolas", 9),
        relief="flat", bd=0,
        selectmode="extended",
    )
    file_scrollbar = ttk.Scrollbar(
        file_list_frame, orient="vertical", command=file_listbox.yview
    )
    file_listbox.configure(yscrollcommand=file_scrollbar.set)

    file_scrollbar.pack(side="right", fill="y")
    file_listbox.pack(side="left", fill="both", expand=True)

    selected_files: list[Path] = []

    def _update_file_count():
        bytecode_count = 0
        source_count = 0
        for f in selected_files:
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(4)
                if header == b'\x1bLua':
                    bytecode_count += 1
                else:
                    source_count += 1
            except Exception:
                source_count += 1
        file_count_label.config(
            text=f"{len(selected_files)} file(s)  |  Bytecode: {bytecode_count}  Source: {source_count}"
        )

    def add_files():
        paths = filedialog.askopenfilenames(
            title="Select Lua files",
            filetypes=[
                ("Lua Files", "*.lua"),
                ("All Files", "*.*"),
            ],
        )
        for p in paths:
            p = Path(p)
            if p not in selected_files:
                selected_files.append(p)
                file_listbox.insert("end", p.name)
        _update_file_count()

    def add_folder():
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        folder = Path(folder)
        for f in sorted(folder.glob("*.lua")):
            if f not in selected_files:
                selected_files.append(f)
                file_listbox.insert("end", f.name)
        # Also scan files without extension (some bytecode files)
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix == '' and f not in selected_files:
                try:
                    with open(f, 'rb') as fh:
                        if fh.read(4) == b'\x1bLua':
                            selected_files.append(f)
                            file_listbox.insert("end", f.name)
                except Exception:
                    pass
        _update_file_count()

    def remove_selected():
        indices = list(file_listbox.curselection())
        for i in reversed(indices):
            file_listbox.delete(i)
            selected_files.pop(i)
        _update_file_count()

    def clear_files():
        file_listbox.delete(0, "end")
        selected_files.clear()
        _update_file_count()

    # ── File buttons ──────────────────────────────────────────
    file_btn_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    file_btn_frame.pack(fill="x", padx=12, pady=4)

    for text, cmd in [("+ Add Files", add_files),
                      ("📁 Add Folder", add_folder),
                      ("✕ Remove", remove_selected),
                      ("Clear All", clear_files)]:
        tk.Button(
            file_btn_frame, text=text, bg=theme["entry_bg"],
            fg=theme["text"], font=("Segoe UI", 9),
            relief="flat", cursor="hand2", command=cmd,
            activebackground=theme["btn_hover"], activeforeground="#FFF",
        ).pack(side="left", padx=2, pady=2, expand=True, fill="x")

    file_count_label = tk.Label(
        left_panel, text="0 file(s)",
        bg=theme["bg_panel"], fg=theme["text_secondary"],
        font=("Segoe UI", 9),
    )
    file_count_label.pack(padx=12, pady=(0, 6), anchor="w")

    # ── Options ───────────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=12, pady=4)

    tk.Label(
        left_panel, text="Options",
        bg=theme["bg_panel"], fg=theme["text"],
        font=("Segoe UI", 11, "bold"),
    ).pack(padx=12, pady=(8, 4), anchor="w")

    # Output directory
    output_dir_var = tk.StringVar(value="")

    def pick_output_dir():
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            output_dir_var.set(d)

    out_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    out_frame.pack(fill="x", padx=12, pady=2)

    tk.Label(
        out_frame, text="Output folder:", bg=theme["bg_panel"],
        fg=theme["text"], font=("Segoe UI", 9),
    ).pack(anchor="w")

    out_entry_frame = tk.Frame(out_frame, bg=theme["bg_panel"])
    out_entry_frame.pack(fill="x")

    out_entry = tk.Entry(
        out_entry_frame, textvariable=output_dir_var,
        bg=theme["entry_bg"], fg=theme["entry_fg"],
        insertbackground=theme["text"], relief="flat",
        font=("Segoe UI", 9),
    )
    out_entry.pack(side="left", fill="x", expand=True, ipady=3)

    tk.Button(
        out_entry_frame, text="…", bg=theme["entry_bg"],
        fg=theme["text"], font=("Segoe UI", 9, "bold"),
        relief="flat", cursor="hand2", width=3, command=pick_output_dir,
    ).pack(side="right")

    tk.Label(
        out_frame, text="(leave empty = same folder as input)",
        bg=theme["bg_panel"], fg=theme["text_secondary"],
        font=("Segoe UI", 8),
    ).pack(anchor="w")

    # Auto-detect mode checkbox
    auto_detect_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
        left_panel, text="Auto-detect mode (bytecode→decompile, source→compile)",
        variable=auto_detect_var,
        bg=theme["bg_panel"], fg=theme["text"],
        selectcolor=theme["entry_bg"],
        activebackground=theme["bg_panel"],
        activeforeground=theme["text"],
        font=("Segoe UI", 9),
    ).pack(padx=12, pady=2, anchor="w")

    # ── Action buttons ────────────────────────────────────────
    tk.Frame(left_panel, bg=theme["border"], height=1).pack(fill="x", padx=12, pady=8)

    action_frame = tk.Frame(left_panel, bg=theme["bg_panel"])
    action_frame.pack(fill="x", padx=12, pady=(0, 12))

    def _run_in_thread(func):
        threading.Thread(target=func, daemon=True).start()

    def _get_output_path(input_path: Path, suffix: str) -> str:
        out_dir = output_dir_var.get()
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            return os.path.join(out_dir, input_path.stem + suffix)
        return str(input_path.with_name(input_path.stem + suffix))

    def do_decompile():
        if not selected_files:
            messagebox.showwarning("No files", "Please add files to decompile.")
            return
        _log_clear()

        # Filter: only bytecode files
        targets = []
        for f in selected_files:
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(4)
                if header == b'\x1bLua':
                    targets.append(f)
                else:
                    _log(f"  ⊘ Skipped (not bytecode): {f.name}")
            except Exception as e:
                _log(f"  ✗ Error reading {f.name}: {e}")

        if not targets:
            _log("No bytecode files found in selection.")
            return

        _log(f"Decompiling {len(targets)} file(s)...\n")
        status_cb(f"Decompiling {len(targets)} file(s)...")

        def _work():
            success = 0
            for f in targets:
                try:
                    out = _get_output_path(f, "_decompiled.lua")
                    result = decompile_file(str(f), out)
                    if result:
                        _log(f"  ✓ {f.name} → {os.path.basename(out)}")
                        success += 1
                    else:
                        _log(f"  ✗ {f.name}: Decompilation failed")
                except Exception as e:
                    _log(f"  ✗ {f.name}: {e}")
            _log(f"\nDone: {success}/{len(targets)} succeeded")
            status_cb(f"Decompile complete: {success}/{len(targets)}")

        _run_in_thread(_work)

    def do_compile():
        if not selected_files:
            messagebox.showwarning("No files", "Please add files to compile.")
            return
        _log_clear()

        # Filter: only source files (not bytecode)
        targets = []
        for f in selected_files:
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(4)
                if header != b'\x1bLua':
                    targets.append(f)
                else:
                    _log(f"  ⊘ Skipped (already bytecode): {f.name}")
            except Exception as e:
                _log(f"  ✗ Error reading {f.name}: {e}")

        if not targets:
            _log("No source files found in selection.")
            return

        _log(f"Compiling {len(targets)} file(s)...\n")
        status_cb(f"Compiling {len(targets)} file(s)...")

        def _work():
            success = 0
            for f in targets:
                try:
                    out = _get_output_path(f, "_compiled.lua")
                    result = compile_lua_file(str(f), out)
                    if result:
                        _log(f"  ✓ {f.name} → {os.path.basename(out)}")
                        success += 1
                    else:
                        _log(f"  ✗ {f.name}: Compilation failed")
                except Exception as e:
                    _log(f"  ✗ {f.name}: {e}")
            _log(f"\nDone: {success}/{len(targets)} succeeded")
            status_cb(f"Compile complete: {success}/{len(targets)}")

        _run_in_thread(_work)

    def do_auto():
        """Auto-detect: decompile bytecode, compile source"""
        if not selected_files:
            messagebox.showwarning("No files", "Please add files first.")
            return
        _log_clear()

        bytecode_files = []
        source_files = []

        for f in selected_files:
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(4)
                if header == b'\x1bLua':
                    bytecode_files.append(f)
                else:
                    source_files.append(f)
            except Exception as e:
                _log(f"  ✗ Error reading {f.name}: {e}")

        total = len(bytecode_files) + len(source_files)
        _log(f"Auto-processing {total} file(s)...")
        _log(f"  Bytecode → Decompile: {len(bytecode_files)}")
        _log(f"  Source → Compile: {len(source_files)}\n")
        status_cb(f"Processing {total} file(s)...")

        def _work():
            success = 0

            for f in bytecode_files:
                try:
                    out = _get_output_path(f, "_decompiled.lua")
                    result = decompile_file(str(f), out)
                    if result:
                        _log(f"  ✓ [decompile] {f.name} → {os.path.basename(out)}")
                        success += 1
                    else:
                        _log(f"  ✗ [decompile] {f.name}: Failed")
                except Exception as e:
                    _log(f"  ✗ [decompile] {f.name}: {e}")

            for f in source_files:
                try:
                    out = _get_output_path(f, "_compiled.lua")
                    result = compile_lua_file(str(f), out)
                    if result:
                        _log(f"  ✓ [compile] {f.name} → {os.path.basename(out)}")
                        success += 1
                    else:
                        _log(f"  ✗ [compile] {f.name}: Failed")
                except Exception as e:
                    _log(f"  ✗ [compile] {f.name}: {e}")

            _log(f"\nDone: {success}/{total} succeeded")
            status_cb(f"Auto-process complete: {success}/{total}")

        _run_in_thread(_work)

    def do_info():
        if not selected_files:
            messagebox.showwarning("No files", "Please add files to inspect.")
            return
        _log_clear()
        status_cb(f"Inspecting {len(selected_files)} file(s)...")

        def _work():
            for f in selected_files:
                result = luaq_info(str(f))
                _log(result)
                _log("─" * 40)
            status_cb("Info complete")

        _run_in_thread(_work)

    # Big action buttons
    for text, cmd, color in [
        ("🔄  Auto-Detect & Process", do_auto, theme["accent"]),
        ("📖  Decompile (Bytecode → Source)", do_decompile, theme["btn_bg"]),
        ("⚙️  Compile (Source → Bytecode)", do_compile, theme["btn_bg"]),
        ("ℹ️  File Info", do_info, theme["entry_bg"]),
    ]:
        btn = tk.Button(
            action_frame, text=text, bg=color,
            fg=theme["btn_fg"] if color != theme["entry_bg"] else theme["text"],
            font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2", command=cmd,
            activebackground=theme["btn_hover"],
            activeforeground="#FFF",
        )
        btn.pack(fill="x", pady=3, ipady=6)

    # ══════════════════════════════════════════════════════════
    # RIGHT PANEL — Log / Output
    # ══════════════════════════════════════════════════════════

    tk.Label(
        right_panel, text="Output Log",
        bg=theme["bg_panel"], fg=theme["text"],
        font=("Segoe UI", 12, "bold"),
    ).pack(padx=12, pady=(12, 4), anchor="w")

    log_text = tk.Text(
        right_panel,
        bg=theme["entry_bg"], fg=theme["entry_fg"],
        insertbackground=theme["text"],
        font=("Consolas", 10),
        relief="flat", bd=0,
        wrap="word",
        state="disabled",
    )
    log_scroll = ttk.Scrollbar(right_panel, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)

    log_scroll.pack(side="right", fill="y", padx=(0, 4), pady=4)
    log_text.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 12))

    def _log(msg: str):
        def _update():
            log_text.config(state="normal")
            log_text.insert("end", msg + "\n")
            log_text.see("end")
            log_text.config(state="disabled")
        parent.after(0, _update)

    def _log_clear():
        def _update():
            log_text.config(state="normal")
            log_text.delete("1.0", "end")
            log_text.config(state="disabled")
        parent.after(0, _update)

    # Welcome message
    _log("LuaQ Converter ready.")
    _log("Add Lua files using the buttons on the left, then choose an action.")
    _log("")
    _log("Supported operations:")
    _log("  • Auto-Detect: Automatically decompile bytecode & compile source")
    _log("  • Decompile: Lua 5.1 bytecode → readable Lua source")
    _log("  • Compile: Lua source table → Lua 5.1 bytecode")
    _log("  • Info: Display file details (type, constants, structure)")
    _log("─" * 40)

    return main

if __name__ == "__main__":
    main()