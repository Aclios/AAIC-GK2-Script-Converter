import struct
import os
import json
import sys
import traceback
import io

SKIPFILES = ["Backup","proper_name","sce0_PostDebug","map0f","sce1_PostDebug","sce2_PostDebug","sce3_PostDebug","sce4_PostDebug"] #these AAIC files are still using the nds format, so it's useless to try to export them

with open('code_info.json') as f:
    CODE_DICT = json.load(f)

REVERSE_CODE_DICT = {v[0]:k for k,v in CODE_DICT.items()}

def readushort(f):
    return struct.unpack('<H',f.read(2))[0]

def readuint(f):
    return struct.unpack('<I',f.read(4))[0]

def read_xored_ushort(f,key):
    return struct.unpack('<H',XOR(f.read(2),key))[0]

def writeuint(f,value):
    f.write(struct.pack('<I',value))

def writeushort(f,value):
    f.write(struct.pack('<H',value))


def XOR(stream,key):
    xored = bytearray()
    for i in range(len(stream)):
        x1 = key[i%2]
        data = stream[i]
        x1 = str('{0:b}'.format(x1))
        databin = str('{0:b}'.format(data))
        newdata =  int(databin,2) ^ int(x1,2)
        xored.append(newdata)
    return xored

class SPT:
    def __init__(self,filepath):
        with open(filepath,mode='rb') as f:
            self.header = SPTHeader(f)
            self.entry_list = [SPTEntry(f) for _ in range(self.header.entry_count)]

            for entry in self.entry_list:
                entry_data = ""
                current_read_count = 0
                f.seek(entry.offset)

                while current_read_count < entry.read_count:

                    data = read_xored_ushort(f,self.header.XOR_key)

                    if data >= 0xe000 and data < 0xf900: #reserved unicode characters that are used by the game for control codes

                        code = hex(data)[2:].upper()
                        if code not in CODE_DICT:
                            raise Exception(f"Unknown code: {code} ; offset: {hex(f.tell() - 2)}")

                        code_name,args_count,unk = CODE_DICT[code]
                        entry_data += self.readsptcode(f,code_name,args_count)
                        current_read_count += args_count

                    elif data == 0xa:
                        entry_data += "<NextLine>\n"

                    else:
                        entry_data += data.to_bytes(2,'little').decode('utf-16')

                    current_read_count += 1

                entry_data += '<_END_>'
                entry.data = entry_data


    def readsptcode(self,f,code_name,args_count):
        if args_count == 0:
            if code_name in ["PageClear"]:
                return f'<{code_name}>\n\n' #formatting

            else:
                return f"<{code_name}>"

        else:
            arg_list = [str(read_xored_ushort(f,self.header.XOR_key)) for _ in range(args_count)]
            if code_name in ["Msg"]:
                return f'\n<{code_name}:{",".join(arg_list)}>' #formatting

            else:
                return f'<{code_name}:{",".join(arg_list)}>'

    def write_to_txt(self,filepath):
        with open(filepath,mode='x',encoding='utf-8') as f:
            for idx, entry in enumerate(self.entry_list):
                f.write(f'[{idx}, f1={hex(entry.flags1)[2:].upper()}, f2={hex(entry.flags2)[2:].upper()}]\n\n')
                f.write(entry.data)
                f.write('\n\n')

class SPTHeader:
    def __init__(self,f):
        self.magic = f.read(4)
        if self.magic != b' TPS':
            raise Exception(f'Error while reading file: bad magic {self.magic}')
        self.unk = f.read(2) #could be a version number, but it didn't change between nds and aaic
        self.entry_count = readushort(f)
        self.biggest_entry_size = readushort(f)
        self.XOR_key = f.read(2)

class SPTEntry:
    def __init__(self,f):
        self.offset = readuint(f) # /!\ readushort in nds
        self.read_count = readushort(f)
        self.flags1 = readushort(f)
        self.flags2 = readushort(f)
        self.data = ""

class TXT:
    def __init__(self,filepath):
        if filepath.endswith('.txt'):
            with open(filepath,mode='r',encoding='utf-8') as f:
                char = f.read(1)
                while char not in ["[",""]:
                    char = f.read(1)
                self.entries = []
                while True:
                    entry = TXTEntry()
                    entry.idx, entry.flags1, entry.flags2 = self.readtxtentryheader(f)
                    entry.data, flag = self.readtxtentry(f)
                    self.entries.append(entry)
                    if flag:
                        break
                offset = 12 + 10 * len(self.entries)
                for entry in self.entries:
                    entry.byte_data = entry.data_to_bytes()
                    entry.offset = offset
                    entry.read_count = len(entry.byte_data) // 2 - 1
                    offset += len(entry.byte_data)

    def readtxtentryheader(self,f):
        data = ""
        char = f.read(1)
        while char != ']':
            data += char
            char = f.read(1)
        idx, flag1, flag2 = data.split(',')
        return int(idx), int(flag1.replace("f1=","").replace(" ",""),16) , int(flag2.replace("f2=","").replace(" ",""),16)

    def readtxtentry(self,f):
        entry_data = ""
        char = f.read(1)
        while char not in ["[",""]:
            if char not in ["\n","\r"]:
                entry_data += char
            char = f.read(1)
        return entry_data, char == ""

    def write_to_spt(self,filepath):
        with open(filepath,mode='wb') as f:
            f.write(b' TPS')
            writeushort(f,0x100)
            writeushort(f,len(self.entries))
            writeushort(f,max([entry.read_count for entry in self.entries]))
            writeushort(f,0x55aa)
            for entry in self.entries:
                writeuint(f,entry.offset)
                writeushort(f,entry.read_count)
                writeushort(f,entry.flags1)
                writeushort(f,entry.flags2)
            for entry in self.entries:
                f.write(entry.byte_data)


class TXTEntry:
    def __init__(self):
        self.offset = 0
        self.read_count = 0
        self.flags1 = 0
        self.flags2 = 0
        self.data = ""

    def data_to_bytes(self):
        idx = 0
        byte_data = bytearray()
        f = io.StringIO(self.data)
        char = f.read(1)
        while char != '':
            if char == '<':
                char = f.read(1)
                code = ""
                while char != '>':
                    code += char
                    char = f.read(1)
                byte_data += self.parse_code(code)
            else:
                byte_data += char.encode('utf-16')[2:]
            char = f.read(1)
        return XOR(byte_data,b'\xaa\x55')

    def parse_code(self,code_data):
        parse = code_data.split(":")
        code = parse[0]
        if len(parse) == 1:
            if code == 'NextLine':
                return '\n'.encode('utf-16')[2:]
            elif code == '_END_':
                return '\x00'.encode('utf-16')[2:]
            else:
                str_code = REVERSE_CODE_DICT[code]
                return int(str_code,16).to_bytes(2,'little')
        else:
            byte_data = bytearray()
            str_code = REVERSE_CODE_DICT[code]
            byte_data += int(str_code,16).to_bytes(2,'little')
            args = parse[1].split(',')
            for arg in args:
                byte_data += int(arg).to_bytes(2,'little')
            return byte_data




def batch_spt_to_txt(input_dir,output_dir):
    for file in os.listdir(input_dir):
        if file.split('.')[0] in SKIPFILES:
            continue
        try:
            print(f"Converting {file} to txt...")
            script = SPT(os.path.join(input_dir,file))
            script.write_to_txt(os.path.join(output_dir,file+'.txt'))
        except:
            print(f"Error while converting {file}:")
            print(traceback.format_exc())

def batch_txt_to_spt(input_dir,output_dir):
    for file in os.listdir(input_dir):
        if not file.endswith('.txt'):
            continue
        try:
            print(f"Converting {file} to SPT...")
            txt = TXT(os.path.join(input_dir,file))
            txt.write_to_spt(os.path.join(output_dir,file[:-4]))
        except:
            print(f"Error while converting {file}:")
            print(traceback.format_exc())

def main():
    args = sys.argv
    if len(sys.argv) != 4:
        print('Usage: "py AAIC_SPT_converter.py [-spt] [-txt] <input_dir> <output_dir>"')
        return
    if sys.argv[1] == '-spt':
        batch_spt_to_txt(sys.argv[2],sys.argv[3])
    elif sys.argv[1] == '-txt':
        batch_txt_to_spt(sys.argv[2],sys.argv[3])
    else:
        print("Use the -spt option to convert spt to txt, or the -txt option to convert txt to spt.")

if __name__ == '__main__':
    main()