# chui.py
"""
CHUI Converter for Shank 2
Converts CHUI files to JSON and back
"""

import struct
import json
import base64
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set, Tuple
from pathlib import Path


@dataclass
class ConversionResult:
    """نتيجة التحويل - متوافق مع main.py"""
    success: bool
    output_path: Optional[Path] = None
    error: Optional[str] = None
    file_size: int = 0


@dataclass
class UIElement:
    name: str
    offset: int
    element_type: str = "unknown"
    position: Optional[Dict[str, float]] = None
    position_offset: int = 0
    texture: Optional[str] = None
    texture_offset: int = 0
    font: Optional[str] = None
    font_offset: int = 0
    text_content: Optional[str] = None
    text_offset: int = 0
    text_length_byte: int = 0
    sound: Optional[str] = None
    sound_offset: int = 0
    states: List[Dict] = field(default_factory=list)
    children: List['UIElement'] = field(default_factory=list)
    raw_data: bytes = b''
    end_offset: int = 0
    
    def to_dict(self) -> Dict:
        result = {
            'name': self.name, 
            'offset': self.offset,
            'end_offset': self.end_offset,
            'type': self.element_type
        }
        if self.position:
            result['position'] = self.position
            result['position_offset'] = self.position_offset
        if self.texture:
            result['texture'] = self.texture
            result['texture_offset'] = self.texture_offset
        if self.font:
            result['font'] = self.font
            result['font_offset'] = self.font_offset
        if self.text_content:
            result['text_content'] = self.text_content
            result['text_offset'] = self.text_offset
            result['text_length_byte'] = self.text_length_byte
        if self.sound:
            result['sound'] = self.sound
            result['sound_offset'] = self.sound_offset
        if self.states:
            result['states'] = self.states
        if self.children:
            result['children'] = [c.to_dict() for c in self.children]
        return result


class CHUIParser:
    """محلل ملفات CHUI - يحول من CHUI إلى JSON مع حفظ البايتات الخام"""
    
    KNOWN_ELEMENTS = {
        'Achievement', 'Bg', 'Icon', 'Name', 'Goal', 'Progress', 'ProgressBg',
        'ProgressBar', 'OldProgressBar', 'Skin', 'Face', 'ListL', 'ListR',
        'bottomGradient', 'topGradient', 'bottomBar', 'topBar', 'bottom', 'top',
        'buttonBack', 'buttonMeta1', 'buttonMeta2', 'Title', 'Description',
        'Left', 'Right', 'Center', 'Header', 'Footer', 'Content', 'Frame',
        'Panel', 'Window', 'Dialog', 'Menu', 'Item', 'Button', 'Label',
        'Slider', 'Checkbox', 'Radio', 'Dropdown', 'Scrollbar', 'Tooltip'
    }
    
    VISUAL_ELEMENTS = {'Bg', 'Icon', 'Face', 'Skin', 'ProgressBg', 'ProgressBar',
                       'OldProgressBar', 'bottomGradient', 'topGradient', 
                       'bottomBar', 'topBar'}
    
    TEXT_ELEMENTS = {'Name', 'Goal', 'Progress', 'Title', 'Description', 'Label'}
    
    CONTAINER_ELEMENTS = {'Achievement', 'ListL', 'ListR', 'buttonBack', 
                          'buttonMeta1', 'buttonMeta2', 'Panel', 'Window',
                          'Dialog', 'Menu', 'Frame', 'Content'}
    
    KNOWN_FONTS = {'flying24', 'bronic24', 'bronic24_no_outline', 'bronic50', 'antilles50'}
    
    SOUND_PATTERNS = {'buttonclick', 'click', 'hover', 'select', 'back', 'confirm'}
    
    def __init__(self, filepath: str = None, data: bytes = None, debug: bool = False):
        if filepath:
            with open(filepath, 'rb') as f:
                self.data = bytearray(f.read())
        elif data:
            self.data = bytearray(data)
        else:
            raise ValueError("Must provide filepath or data")
        
        self.original_data = bytes(self.data)
        self.pos = 0
        self.debug = debug
        self.all_textures: Set[str] = set()
        self.seen_elements: Set[tuple] = set()
    
    def debug_print(self, msg: str):
        if self.debug:
            print(f"[DEBUG] {msg}")
    
    def parse(self) -> Dict:
        header = self.parse_header()
        self.pos = 12
        
        elements = []
        while self.pos < len(self.data) - 4:
            element = self.parse_next_element()
            if element:
                elem_key = (element.name, element.offset)
                if elem_key not in self.seen_elements:
                    if element.position or element.texture or element.text_content or element.font:
                        elements.append(element)
                        self.seen_elements.add(elem_key)
        
        raw_base64 = base64.b64encode(self.original_data).decode('ascii')
        
        return {
            'header': header,
            'elements': [e.to_dict() for e in elements],
            'textures': sorted(self.all_textures),
            'stats': self.calculate_stats(elements),
            'raw_data': raw_base64,
            'file_size': len(self.original_data)
        }
    
    def parse_header(self) -> Dict:
        return {
            'magic': struct.unpack('<H', self.data[0:2])[0],
            'version': struct.unpack('<H', self.data[2:4])[0],
            'element_count': struct.unpack('<I', self.data[4:8])[0],
            'unknown': struct.unpack('<I', self.data[8:12])[0]
        }
    
    def clean_string(self, s: str) -> str:
        if not s:
            return s
        s = ''.join(c for c in s if ord(c) >= 32 or c in '\n\r\t')
        return s.strip()
    
    def is_valid_text_content(self, s: str) -> bool:
        if not s or len(s) < 2:
            return False
        if s in self.KNOWN_ELEMENTS:
            return False
        if re.match(r'^[a-z]+[A-Z][a-zA-Z]*$', s):
            return False
        if s.lower().startswith('button'):
            return False
        ui_keywords = {'top', 'bottom', 'left', 'right', 'center', 'header', 
                       'footer', 'content', 'frame', 'panel', 'window', 'dialog',
                       'menu', 'item', 'label', 'slider', 'checkbox', 'radio'}
        if s.lower() in ui_keywords:
            return False
        if not (s[0].isalnum() or s[0] in '"\'('):
            return False
        printable_count = sum(1 for c in s if c.isprintable())
        if printable_count / len(s) < 0.9:
            return False
        return True
    
    def read_string_at(self, pos: int) -> Optional[Tuple[str, int]]:
        if pos < 0 or pos >= len(self.data):
            return None
        
        length = self.data[pos]
        if length == 0 or length > 100:
            return None
        
        if pos + 1 + length > len(self.data):
            return None
        
        name_bytes = self.data[pos + 1:pos + 1 + length]
        
        printable = sum(1 for b in name_bytes if 32 <= b <= 126 or b == 0)
        if printable < length * 0.8:
            return None
        
        try:
            return (name_bytes.decode('utf-8'), length)
        except:
            return None
    
    def read_string(self) -> Optional[str]:
        result = self.read_string_at(self.pos)
        return result[0] if result else None
    
    def peek_string(self, offset: int = 0) -> Optional[str]:
        result = self.read_string_at(self.pos + offset)
        return result[0] if result else None
    
    def is_texture_path(self, s: str) -> bool:
        return s.endswith('.tex') if s else False
    
    def is_ui_element(self, s: str) -> bool:
        return s in self.KNOWN_ELEMENTS if s else False
    
    def is_font(self, s: str) -> bool:
        if not s:
            return False
        return s in self.KNOWN_FONTS or bool(re.match(r'(flying|bronic|antilles)\d+', s))
    
    def is_sound_or_action(self, s: str) -> bool:
        if not s:
            return False
        if s.startswith('|'):
            return True
        s_lower = s.lower()
        for pattern in self.SOUND_PATTERNS:
            if pattern in s_lower:
                return True
        if s_lower.startswith('button') and '_' in s_lower:
            return True
        return False
    
    def parse_next_element(self) -> Optional[UIElement]:
        start_pos = self.pos
        max_search = 100
        
        for _ in range(max_search):
            name = self.read_string()
            
            if name and self.is_ui_element(name):
                element = UIElement(name=name, offset=self.pos)
                self.pos += 1 + len(name)
                
                if name in self.VISUAL_ELEMENTS:
                    element.element_type = "visual"
                elif name in self.TEXT_ELEMENTS:
                    element.element_type = "text"
                elif name in self.CONTAINER_ELEMENTS:
                    element.element_type = "container"
                
                pos_result = self.try_parse_position()
                if pos_result:
                    element.position = pos_result[0]
                    element.position_offset = pos_result[1]
                
                if element.element_type == "visual":
                    self.parse_visual_data(element)
                elif element.element_type == "text":
                    self.parse_text_data(element)
                elif element.element_type == "container":
                    self.parse_container_data(element)
                
                element.end_offset = self.pos
                return element
            
            self.pos += 1
            if self.pos >= len(self.data) - 4:
                break
        
        return None
    
    def try_parse_position(self) -> Optional[Tuple[Dict, int]]:
        if self.pos + 12 > len(self.data):
            return None
        
        try:
            floats = struct.unpack('<3f', self.data[self.pos:self.pos + 12])
            valid = all((-100 < f < 100) and (abs(f) > 1e-10 or f == 0.0) for f in floats)
            if valid:
                pos_offset = self.pos
                self.pos += 12
                return ({'x': floats[0], 'y': floats[1], 'z': floats[2]}, pos_offset)
        except:
            pass
        return None
    
    def parse_visual_data(self, element: UIElement):
        states = []
        first_texture = None
        first_texture_offset = 0
        scan_start = self.pos
        
        while self.pos < len(self.data) - 4:
            peek = self.peek_string()
            if peek and self.is_ui_element(peek):
                break
            
            result = self.read_string_at(self.pos)
            if result:
                s, length = result
                if self.is_texture_path(s):
                    self.all_textures.add(s)
                    if first_texture is None:
                        first_texture = s
                        first_texture_offset = self.pos
                    else:
                        states.append({'texture': s, 'offset': self.pos})
                    self.pos += 1 + length
                    continue
            
            self.pos += 1
            if self.pos - scan_start > 2000:
                break
        
        element.texture = first_texture
        element.texture_offset = first_texture_offset
        if states:
            element.states = states
    
    def parse_text_data(self, element: UIElement):
        scan_start = self.pos
        found_texts = []
        
        while self.pos < len(self.data) - 4:
            peek = self.peek_string()
            if peek and self.is_ui_element(peek):
                break
            
            result = self.read_string_at(self.pos)
            if result:
                text, length = result
                current_offset = self.pos
                
                if self.is_texture_path(text):
                    self.pos += 1 + length
                    continue
                
                if self.is_font(text):
                    element.font = text
                    element.font_offset = current_offset
                    self.pos += 1 + length
                    break
                
                clean_text = self.clean_string(text)
                
                if self.is_valid_text_content(clean_text) and not self.is_sound_or_action(clean_text):
                    found_texts.append({
                        'text': clean_text,
                        'offset': current_offset,
                        'length_byte': length
                    })
                
                self.pos += 1 + length
                continue
            
            self.pos += 1
            if self.pos - scan_start > 200:
                break
        
        if found_texts:
            best = max(found_texts, key=lambda x: len(x['text']))
            element.text_content = best['text']
            element.text_offset = best['offset']
            element.text_length_byte = best['length_byte']
    
    def parse_container_data(self, element: UIElement):
        scan_start = self.pos
        found_texts = []
        
        while self.pos < len(self.data) - 4:
            peek = self.peek_string()
            if peek and self.is_ui_element(peek):
                break
            
            result = self.read_string_at(self.pos)
            if result:
                s, length = result
                current_offset = self.pos
                clean_s = self.clean_string(s)
                
                if not clean_s or len(clean_s) < 2:
                    self.pos += 1 + length
                    continue
                
                if self.is_font(clean_s):
                    element.font = clean_s
                    element.font_offset = current_offset
                elif self.is_sound_or_action(s):
                    element.sound = clean_s
                    element.sound_offset = current_offset
                elif self.is_texture_path(clean_s):
                    pass
                elif self.is_valid_text_content(clean_s):
                    found_texts.append({
                        'text': clean_s,
                        'offset': current_offset,
                        'length_byte': length
                    })
                
                self.pos += 1 + length
                continue
            
            self.pos += 1
            if self.pos - scan_start > 150:
                break
        
        if found_texts:
            best = max(found_texts, key=lambda x: len(x['text']))
            element.text_content = best['text']
            element.text_offset = best['offset']
            element.text_length_byte = best['length_byte']
    
    def calculate_stats(self, elements: List[UIElement]) -> Dict:
        stats = {
            'total': len(elements), 
            'visual': 0, 
            'text': 0, 
            'container': 0, 
            'textures': len(self.all_textures),
            'states_total': 0,
            'with_sound': 0
        }
        for e in elements:
            if e.element_type == 'visual':
                stats['visual'] += 1
            elif e.element_type == 'text':
                stats['text'] += 1
            elif e.element_type == 'container':
                stats['container'] += 1
            stats['states_total'] += len(e.states)
            if e.sound:
                stats['with_sound'] += 1
        return stats


class CHUIBuilder:
    """باني ملفات CHUI - يعدل البايتات الخام مباشرة"""
    
    def __init__(self, json_data: Dict, debug: bool = False):
        self.json_data = json_data
        self.debug = debug
        
        if 'raw_data' in json_data:
            self.data = bytearray(base64.b64decode(json_data['raw_data']))
        else:
            raise ValueError("JSON must contain 'raw_data' field. Re-parse the CHUI file first.")
        
        self.original_size = json_data.get('file_size', len(self.data))
    
    def debug_print(self, msg: str):
        if self.debug:
            print(f"[BUILD] {msg}")
    
    def write_string_at(self, offset: int, new_string: str, original_length: int) -> bool:
        encoded = new_string.encode('utf-8')
        
        if len(encoded) > original_length:
            self.debug_print(f"Warning: Truncating string from {len(encoded)} to {original_length}")
            encoded = encoded[:original_length]
        
        self.data[offset] = len(encoded)
        
        for i, b in enumerate(encoded):
            self.data[offset + 1 + i] = b
        
        for i in range(len(encoded), original_length):
            self.data[offset + 1 + i] = 0
        
        self.debug_print(f"Wrote '{new_string}' at offset {offset}")
        return True
    
    def apply_modifications(self):
        elements = self.json_data.get('elements', [])
        
        for elem in elements:
            self._apply_element_modifications(elem)
    
    def _apply_element_modifications(self, elem: Dict):
        if elem.get('text_content') and elem.get('text_offset', 0) > 0:
            offset = elem['text_offset']
            original_length = elem.get('text_length_byte', len(elem['text_content']))
            self.write_string_at(offset, elem['text_content'], original_length)
        
        if elem.get('texture') and elem.get('texture_offset', 0) > 0:
            offset = elem['texture_offset']
            original_length = self.data[offset]
            self.write_string_at(offset, elem['texture'], original_length)
        
        if elem.get('font') and elem.get('font_offset', 0) > 0:
            offset = elem['font_offset']
            original_length = self.data[offset]
            self.write_string_at(offset, elem['font'], original_length)
        
        if elem.get('position') and elem.get('position_offset', 0) > 0:
            offset = elem['position_offset']
            pos = elem['position']
            pos_bytes = struct.pack('<3f', pos['x'], pos['y'], pos['z'])
            self.data[offset:offset + 12] = pos_bytes
            self.debug_print(f"Wrote position at offset {offset}")
        
        if elem.get('states'):
            for state in elem['states']:
                if state.get('texture') and state.get('offset', 0) > 0:
                    offset = state['offset']
                    original_length = self.data[offset]
                    self.write_string_at(offset, state['texture'], original_length)
        
        if elem.get('children'):
            for child in elem['children']:
                self._apply_element_modifications(child)
    
    def build(self) -> bytes:
        self.apply_modifications()
        
        if len(self.data) != self.original_size:
            self.debug_print(f"Warning: Size changed from {self.original_size} to {len(self.data)}")
        
        self.debug_print(f"Final size: {len(self.data)} bytes (original: {self.original_size})")
        return bytes(self.data)
    
    def save(self, filepath: str):
        data = self.build()
        with open(filepath, 'wb') as f:
            f.write(data)
        print(f"Saved CHUI: {filepath} ({len(data)} bytes)")


class CHUIConverter:
    """
    محول CHUI الرئيسي - متوافق مع main.py
    يوفر واجهة extract و rebuild مثل KTEXConverter
    """
    
    def __init__(self, debug: bool = False):
        self.debug = debug
    
    def extract(self, input_path: Path) -> ConversionResult:
        """
        استخراج CHUI إلى JSON
        
        Args:
            input_path: مسار ملف CHUI
            
        Returns:
            ConversionResult مع نتيجة العملية
        """
        try:
            input_path = Path(input_path)
            
            if not input_path.exists():
                return ConversionResult(
                    success=False,
                    error=f"File not found: {input_path}"
                )
            
            if not input_path.suffix.lower() == '.chui':
                return ConversionResult(
                    success=False,
                    error=f"Not a CHUI file: {input_path}"
                )
            
            # تحليل الملف
            parser = CHUIParser(filepath=str(input_path), debug=self.debug)
            result = parser.parse()
            
            # حفظ JSON
            output_path = input_path.with_suffix('.json')
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            return ConversionResult(
                success=True,
                output_path=output_path,
                file_size=result['file_size']
            )
            
        except Exception as e:
            return ConversionResult(
                success=False,
                error=str(e)
            )
    
    def rebuild(self, input_path: Path) -> ConversionResult:
        """
        إعادة بناء JSON إلى CHUI
        
        Args:
            input_path: مسار ملف JSON
            
        Returns:
            ConversionResult مع نتيجة العملية
        """
        try:
            input_path = Path(input_path)
            
            if not input_path.exists():
                return ConversionResult(
                    success=False,
                    error=f"File not found: {input_path}"
                )
            
            if not input_path.suffix.lower() == '.json':
                return ConversionResult(
                    success=False,
                    error=f"Not a JSON file: {input_path}"
                )
            
            # قراءة JSON
            with open(input_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # التحقق من وجود raw_data
            if 'raw_data' not in json_data:
                return ConversionResult(
                    success=False,
                    error="JSON file doesn't contain 'raw_data'. Please re-extract the original CHUI file."
                )
            
            # بناء الملف
            builder = CHUIBuilder(json_data, debug=self.debug)
            output_data = builder.build()
            
            # حفظ CHUI
            output_path = input_path.with_suffix('.chui')
            
            with open(output_path, 'wb') as f:
                f.write(output_data)
            
            return ConversionResult(
                success=True,
                output_path=output_path,
                file_size=len(output_data)
            )
            
        except Exception as e:
            return ConversionResult(
                success=False,
                error=str(e)
            )
    
    def validate_chui(self, filepath: Path) -> bool:
        """التحقق من صحة ملف CHUI"""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(12)
            
            if len(header) < 12:
                return False
            
            # يمكن إضافة المزيد من التحققات هنا
            return True
            
        except:
            return False


# ================== Helper Functions ==================

def parse_chui(filepath: str, debug: bool = False) -> Dict:
    """تحليل ملف CHUI"""
    parser = CHUIParser(filepath=filepath, debug=debug)
    return parser.parse()


def build_chui(json_data: Dict, output_path: str, debug: bool = False):
    """بناء ملف CHUI من JSON"""
    builder = CHUIBuilder(json_data, debug=debug)
    builder.save(output_path)


def json_to_chui(json_filepath: str, output_path: str = None, debug: bool = False):
    """تحويل JSON إلى CHUI"""
    with open(json_filepath, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    if 'raw_data' not in json_data:
        raise ValueError("JSON file doesn't contain raw_data. Please re-parse the original CHUI file.")
    
    if output_path is None:
        output_path = json_filepath.replace('.json', '.chui')
    
    build_chui(json_data, output_path, debug=debug)


def chui_to_json(chui_filepath: str, output_path: str = None, debug: bool = False):
    """تحويل CHUI إلى JSON"""
    result = parse_chui(chui_filepath, debug=debug)
    
    if output_path is None:
        output_path = chui_filepath.replace('.chui', '.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"Saved JSON: {output_path} (raw_data: {len(result['raw_data'])} chars)")
    return result


# ================== CLI Interface ==================

def main():
    import sys
    
    if len(sys.argv) < 2:
        print("=" * 60)
        print("CHUI Tool - Parse & Build CHUI Files")
        print("=" * 60)
        print("\nUsage:")
        print("  python chui.py <file.chui>  -> Create file.json")
        print("  python chui.py <file.json>  -> Create file.chui")
        print("")
        print("Options:")
        print("  --debug    Show debug information")
        print("")
        print("Note: JSON file contains raw binary data")
        print("      Output file will be exactly the same size")
        sys.exit(1)
    
    debug_mode = '--debug' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--debug']
    filepath = args[0]
    
    if filepath.endswith('.chui'):
        result = chui_to_json(filepath, debug=debug_mode)
        
        print("\n" + "=" * 60)
        print("CHUI Parser - Extraction Complete")
        print("=" * 60)
        print(f"\nHeader: {result['header']}")
        print(f"Stats: {result['stats']}")
        print(f"File size: {result['file_size']} bytes")
        
        print(f"\nElements ({len(result['elements'])}):")
        for elem in result['elements']:
            icon = {'visual': '[V]', 'text': '[T]', 'container': '[C]'}.get(elem['type'], '[?]')
            line = f"   {icon} {elem['name']} @{elem['offset']}"
            if elem.get('texture'):
                line += f" -> {elem['texture']}"
            if elem.get('font'):
                line += f" [{elem['font']}]"
            if elem.get('text_content'):
                tc = elem['text_content']
                if len(tc) > 35:
                    tc = tc[:35] + '...'
                line += f' "{tc}"'
            if elem.get('text_offset'):
                line += f" (text@{elem['text_offset']})"
            print(line)
    
    elif filepath.endswith('.json'):
        json_to_chui(filepath, debug=debug_mode)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        output_path = filepath.replace('.json', '.chui')
        import os
        if os.path.exists(output_path):
            new_size = os.path.getsize(output_path)
            original_size = json_data.get('file_size', 0)
            
            print(f"\nBuild complete!")
            print(f"   Original size: {original_size} bytes")
            print(f"   New size:      {new_size} bytes")
            
            if new_size == original_size:
                print(f"   Sizes match perfectly!")
            else:
                print(f"   Size difference: {new_size - original_size} bytes")
    
    else:
        print(f"Unknown file type: {filepath}")
        print("   Supported: .chui, .json")
        sys.exit(1)


if __name__ == "__main__":
    main()