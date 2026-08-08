#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scramble_27_opcodes.py -- 打乱 CPython 2.7.3 的 opcode 编号

以 Lib/opcode.py 为事实来源，重排所有真实 opcode 的编号，并同步更新
hasconst / hasname / hasjrel / hasjabs / haslocal / hascompare / hasfree 列表
与 EXTENDED_ARG 常量。同时同步更新 Include/opcode.h 中的宏定义、
Python/frozen.c 中的冻结字节码（清空）以及 Python/import.c 中的 MAGIC 号。

用法:
    python scramble_27_opcodes.py --seed 42     # 用随机数种子 42 随机打乱
    python scramble_27_opcodes.py --reverse     # 在每个可交换组内"反转"编号顺序(默认)
    python scramble_27_opcodes.py --restore     # 恢复官方原始编号
    python scramble_27_opcodes.py --check       # 仅校验当前文件是否已是官方原始编号

保持不动: HAVE_ARGUMENT = 90 边界不变。

硬约束(依据 CPython 2.7.3 源码):
  * 无参数 opcode 必须 < HAVE_ARGUMENT(90)，带参数 opcode 必须 >= 90：
    Python/compile.c 依赖 HAS_ARG(op) 决定是否发射 oparg。
  * SLICE+0..3 / STORE_SLICE+0..3 / DELETE_SLICE+0..3 必须连续且按顺序：
    Python/ceval.c 中使用 case SLICE+0 / case STORE_SLICE+1 等形式。
  * CALL_FUNCTION / CALL_FUNCTION_VAR / CALL_FUNCTION_KW / CALL_FUNCTION_VAR_KW
    必须连续且按顺序：ceval.c 用 (opcode - CALL_FUNCTION) & 3 区分变体。

"可交换组" = Lib/opcode.py 中按空行划分的 opcode 族（与 bytecodes 分族一致），
--reverse 在每组内部反转编号顺序；--seed 则在"无参池 [0,90) 与带参池 [90,256)"
两个可交换池内做带种子的随机排列（原子单元保持连续）。
"""

import argparse
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPCODE_PY = os.path.join(HERE, "Lib", "opcode.py")
OPCODE_H = os.path.join(HERE, "Include", "opcode.h")
FROZEN_C = os.path.join(HERE, "Python", "frozen.c")
IMPORT_C = os.path.join(HERE, "Python", "import.c")

HAVE_ARGUMENT = 90
PINNED = set()  # 2.7 中没有强制固定的 opcode（HAVE_ARGUMENT 是边界不是 opcode）

# ---------------------------------------------------------------------------
# CPython 2.7.3 官方 opcode 表（Lib/opcode.py 声明顺序），
# 分组与 Lib/opcode.py 中的空行分隔完全一致。
# 特殊原子单元用元组嵌套表示：(base_name, [name0, name1, ...])，
# 它们必须保持连续且按顺序出现。
# ---------------------------------------------------------------------------
STOCK_GROUPS = [
    # --- 无参 opcode (< 90) ---
    [("STOP_CODE", 0), ("POP_TOP", 1), ("ROT_TWO", 2),
     ("ROT_THREE", 3), ("DUP_TOP", 4), ("ROT_FOUR", 5)],
    [("NOP", 9), ("UNARY_POSITIVE", 10), ("UNARY_NEGATIVE", 11),
     ("UNARY_NOT", 12), ("UNARY_CONVERT", 13)],
    [("UNARY_INVERT", 15)],
    [("BINARY_POWER", 19), ("BINARY_MULTIPLY", 20), ("BINARY_DIVIDE", 21),
     ("BINARY_MODULO", 22), ("BINARY_ADD", 23), ("BINARY_SUBTRACT", 24),
     ("BINARY_SUBSCR", 25), ("BINARY_FLOOR_DIVIDE", 26),
     ("BINARY_TRUE_DIVIDE", 27), ("INPLACE_FLOOR_DIVIDE", 28),
     ("INPLACE_TRUE_DIVIDE", 29)],
    # 原子单元: SLICE+0..3
    [("SLICE+0", 30), ("SLICE+1", 31), ("SLICE+2", 32), ("SLICE+3", 33)],
    # 原子单元: STORE_SLICE+0..3
    [("STORE_SLICE+0", 40), ("STORE_SLICE+1", 41),
     ("STORE_SLICE+2", 42), ("STORE_SLICE+3", 43)],
    # 原子单元: DELETE_SLICE+0..3
    [("DELETE_SLICE+0", 50), ("DELETE_SLICE+1", 51),
     ("DELETE_SLICE+2", 52), ("DELETE_SLICE+3", 53)],
    [("STORE_MAP", 54), ("INPLACE_ADD", 55), ("INPLACE_SUBTRACT", 56),
     ("INPLACE_MULTIPLY", 57), ("INPLACE_DIVIDE", 58), ("INPLACE_MODULO", 59),
     ("STORE_SUBSCR", 60), ("DELETE_SUBSCR", 61), ("BINARY_LSHIFT", 62),
     ("BINARY_RSHIFT", 63), ("BINARY_AND", 64), ("BINARY_XOR", 65),
     ("BINARY_OR", 66), ("INPLACE_POWER", 67), ("GET_ITER", 68)],
    [("PRINT_EXPR", 70), ("PRINT_ITEM", 71), ("PRINT_NEWLINE", 72),
     ("PRINT_ITEM_TO", 73), ("PRINT_NEWLINE_TO", 74), ("INPLACE_LSHIFT", 75),
     ("INPLACE_RSHIFT", 76), ("INPLACE_AND", 77), ("INPLACE_XOR", 78),
     ("INPLACE_OR", 79), ("BREAK_LOOP", 80), ("WITH_CLEANUP", 81),
     ("LOAD_LOCALS", 82), ("RETURN_VALUE", 83), ("IMPORT_STAR", 84),
     ("EXEC_STMT", 85), ("YIELD_VALUE", 86), ("POP_BLOCK", 87),
     ("END_FINALLY", 88), ("BUILD_CLASS", 89)],
    # --- 带参 opcode (>= 90) ---
    [("STORE_NAME", 90), ("DELETE_NAME", 91), ("UNPACK_SEQUENCE", 92),
     ("FOR_ITER", 93), ("LIST_APPEND", 94)],
    [("STORE_ATTR", 95), ("DELETE_ATTR", 96), ("STORE_GLOBAL", 97),
     ("DELETE_GLOBAL", 98), ("DUP_TOPX", 99), ("LOAD_CONST", 100)],
    [("LOAD_NAME", 101), ("BUILD_TUPLE", 102), ("BUILD_LIST", 103),
     ("BUILD_SET", 104), ("BUILD_MAP", 105), ("LOAD_ATTR", 106),
     ("COMPARE_OP", 107), ("IMPORT_NAME", 108), ("IMPORT_FROM", 109),
     ("JUMP_FORWARD", 110)],
    [("JUMP_IF_FALSE_OR_POP", 111), ("JUMP_IF_TRUE_OR_POP", 112),
     ("JUMP_ABSOLUTE", 113), ("POP_JUMP_IF_FALSE", 114),
     ("POP_JUMP_IF_TRUE", 115)],
    [("LOAD_GLOBAL", 116)],
    [("CONTINUE_LOOP", 119), ("SETUP_LOOP", 120), ("SETUP_EXCEPT", 121),
     ("SETUP_FINALLY", 122)],
    [("LOAD_FAST", 124), ("STORE_FAST", 125), ("DELETE_FAST", 126)],
    [("RAISE_VARARGS", 130)],
    # 原子单元: CALL_FUNCTION 家族 4 个必须连续有序
    [("CALL_FUNCTION", 131), ("CALL_FUNCTION_VAR", 140),
     ("CALL_FUNCTION_KW", 141), ("CALL_FUNCTION_VAR_KW", 142)],
    [("MAKE_FUNCTION", 132), ("BUILD_SLICE", 133)],
    [("MAKE_CLOSURE", 134), ("LOAD_CLOSURE", 135), ("LOAD_DEREF", 136),
     ("STORE_DEREF", 137)],
    [("SETUP_WITH", 143)],
    [("EXTENDED_ARG", 145), ("SET_ADD", 146), ("MAP_ADD", 147)],
]

# 原子单元（必须保持连续且按顺序）: 列出每组内的名字列表
ATOMIC_UNITS = [
    ("SLICE+0", "SLICE+1", "SLICE+2", "SLICE+3"),
    ("STORE_SLICE+0", "STORE_SLICE+1", "STORE_SLICE+2", "STORE_SLICE+3"),
    ("DELETE_SLICE+0", "DELETE_SLICE+1", "DELETE_SLICE+2", "DELETE_SLICE+3"),
    ("CALL_FUNCTION", "CALL_FUNCTION_VAR", "CALL_FUNCTION_KW",
     "CALL_FUNCTION_VAR_KW"),
]
ATOMIC_SET = set()
for unit in ATOMIC_UNITS:
    ATOMIC_SET.update(unit)

# 展平成 (name, value) 列表
STOCK = [item for group in STOCK_GROUPS for item in group]
STOCK_MAP = dict(STOCK)
STOCK_VAL_TO_NAME = {v: n for n, v in STOCK}

# Lib/opcode.py 中 has* 列表与 opcode 的对应关系（按文件内出现顺序）
HAS_LISTS = {
    "hasconst": ["LOAD_CONST"],
    "hascompare": ["COMPARE_OP"],
    "haslocal": ["LOAD_FAST", "STORE_FAST", "DELETE_FAST"],
    "hasfree": ["LOAD_CLOSURE", "LOAD_DEREF", "STORE_DEREF"],
}


# ---------------------------------------------------------------------------
# Lib/opcode.py 文本解析
# ---------------------------------------------------------------------------
DECL_RE = re.compile(
    r"^(?P<ind>\s*)(?P<fn>def_op|name_op|jrel_op|jabs_op)"
    r"\((?P<quote>['\"])(?P<name>[A-Za-z_+][A-Za-z0-9_+]*)(?P=quote),"
    r"\s*(?P<num>\d+)\)")
HAS_RE = re.compile(r"^(?P<kind>hasconst|hasname|hasjrel|hasjabs|"
                    r"haslocal|hascompare|hasfree)"
                    r"\.append\((?P<num>\d+)\)")
EXT_RE = re.compile(r"^EXTENDED_ARG = (?P<num>\d+)")
HAVE_RE = re.compile(r"^HAVE_ARGUMENT = (?P<num>\d+)")


def parse_opcode_py(path=OPCODE_PY):
    """返回 (lines, decls, has_lines, ext_line)。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    decls, has_lines = [], []
    ext_line = None
    have_line = None
    for i, line in enumerate(lines):
        m = DECL_RE.match(line)
        if m:
            decls.append((i, m))
            continue
        m = HAS_RE.match(line)
        if m:
            has_lines.append((i, m))
            continue
        m = EXT_RE.match(line)
        if m:
            ext_line = (i, m)
            continue
        m = HAVE_RE.match(line)
        if m:
            have_line = (i, m)
    names = [m.group("name") for _, m in decls]
    if set(names) != set(STOCK_MAP):
        missing = sorted(set(STOCK_MAP) - set(names))
        extra = sorted(set(names) - set(STOCK_MAP))
        raise SystemExit(
            "Lib/opcode.py opcode 集合与本脚本内置的 2.7 表不一致"
            f"\n  缺少: {missing}\n  多余: {extra}")
    if have_line is not None:
        val = int(have_line[1].group("num"))
        if val != HAVE_ARGUMENT:
            raise SystemExit(
                f"Lib/opcode.py 中 HAVE_ARGUMENT = {val}，预期 {HAVE_ARGUMENT}")
    return lines, decls, has_lines, ext_line


def _replace_num(line, match, newval):
    start, end = match.span("num")
    return line[:start] + str(newval) + line[end:]


def apply_mapping_to_opcode_py(lines, decls, has_lines, ext_line, mapping):
    """按 mapping 重写 Lib/opcode.py，返回 (新内容, 是否变化)。"""
    new_lines = list(lines)
    for i, m in decls:
        new_lines[i] = _replace_num(new_lines[i], m, mapping[m.group("name")])
    # has* 行：按 HAS_LISTS 定义的顺序逐个替换
    has_iter = {k: iter(names) for k, names in HAS_LISTS.items()}
    # 注意：hasname / hasjrel / hasjabs 的 opcode 是在声明时通过
    # name_op / jrel_op / jabs_op 函数自动加入的，不需要显式 .append()，
    # 因此这里只处理显式 append 的 hasconst / hascompare / haslocal / hasfree
    for i, m in has_lines:
        kind = m.group("kind")
        if kind in has_iter:
            try:
                name = next(has_iter[kind])
                new_lines[i] = _replace_num(new_lines[i], m, mapping[name])
            except StopIteration:
                pass
    if ext_line is not None:
        i, m = ext_line
        new_lines[i] = _replace_num(new_lines[i], m, mapping["EXTENDED_ARG"])
    changed = new_lines != lines
    return new_lines, changed


# ---------------------------------------------------------------------------
# Include/opcode.h 文本解析与生成
# ---------------------------------------------------------------------------
DEFINE_RE = re.compile(
    r"^#define\s+(?P<name>[A-Z][A-Z0-9_+]*)\s+(?P<num>\d+)\b")
# "Also uses 31-33" 形式的注释（用于 SLICE / STORE_SLICE / DELETE_SLICE）
ALSO_USES_RE = re.compile(
    r"(?P<prefix>/\* Also uses )(?P<lo>\d+)-(?P<hi>\d+)(?P<suffix> \*/)")

# C 宏名 -> Python opcode.py 名的映射（仅针对命名不同的原子单元基准）
C_TO_PY_NAME = {
    "SLICE": "SLICE+0",
    "STORE_SLICE": "STORE_SLICE+0",
    "DELETE_SLICE": "DELETE_SLICE+0",
}
PY_TO_C_NAME = {v: k for k, v in C_TO_PY_NAME.items()}


def _py_name(c_name):
    """将 C 宏名转换为 opcode.py 中的名字。"""
    return C_TO_PY_NAME.get(c_name, c_name)


def parse_opcode_h(path=OPCODE_H):
    """解析 opcode.h，返回 (lines, defs, also_uses_pairs)。
    defs: [(lineno, match, py_name)]
    also_uses_pairs: [(lineno, match, base_py_name)]  每个 also_uses 对应的基准 opcode 名
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    defs = []
    also_uses_pairs = []
    last_py_name = None
    for i, line in enumerate(lines):
        m = DEFINE_RE.match(line)
        if m:
            py_name = _py_name(m.group("name"))
            if py_name in STOCK_MAP:
                defs.append((i, m, py_name))
                last_py_name = py_name
            continue
        m = ALSO_USES_RE.search(line)
        if m and last_py_name is not None:
            # 这个 also_uses 注释属于它上面最近的那个 define
            also_uses_pairs.append((i, m, last_py_name))
    return lines, defs, also_uses_pairs


def apply_mapping_to_opcode_h(lines, defs, also_uses_pairs, mapping):
    """按 mapping 重写 Include/opcode.h。"""
    new_lines = list(lines)
    # 更新所有 #define 行的数值
    for i, m, py_name in defs:
        if py_name in mapping:
            new_lines[i] = _replace_num(new_lines[i], m, mapping[py_name])
    # 更新 "Also uses X-Y" 注释
    for i, m, base_py_name in also_uses_pairs:
        if base_py_name not in mapping:
            continue
        base_val = mapping[base_py_name]
        # 找到原子单元的大小（通常是 4：+0 +1 +2 +3，also uses 覆盖 +1..+3）
        unit_size = None
        for unit in ATOMIC_UNITS:
            if unit[0] == base_py_name:
                unit_size = len(unit)
                break
        if unit_size is None:
            continue
        also_lo = base_val + 1
        also_hi = base_val + unit_size - 1
        new_lines[i] = (lines[i][:m.start("lo")] + str(also_lo) +
                        "-" + str(also_hi) + lines[i][m.end("hi"):])
    changed = new_lines != lines
    return new_lines, changed


# ---------------------------------------------------------------------------
# 构建打乱映射
# ---------------------------------------------------------------------------

def _atomic_base_map():
    """返回 {name: base_name}，原子单元内所有成员都映射到首元素名。"""
    m = {}
    for unit in ATOMIC_UNITS:
        base = unit[0]
        for name in unit:
            m[name] = base
    return m


ATOMIC_BASE = _atomic_base_map()


def _unit_size(name):
    """返回以 name 为首的原子单元大小；非原子返回 1。"""
    if name in ATOMIC_BASE and ATOMIC_BASE[name] == name:
        for unit in ATOMIC_UNITS:
            if unit[0] == name:
                return len(unit)
    return 1


def _unit_members(base_name):
    """返回原子单元成员列表；非原子返回 [base_name]。"""
    for unit in ATOMIC_UNITS:
        if unit[0] == base_name:
            return list(unit)
    return [base_name]


def build_seed_mapping(seed):
    """带种子随机打乱：无参池与带参池内部各自随机排列。
    原子单元作为整体移动，保持内部连续有序。
    """
    rng = random.Random(seed)

    # 收集每个池内的"单元"（原子单元作为整体，单个 opcode 也是单元）
    noarg_units = []  # list of base_name
    arg_units = []
    seen_bases = set()
    for name, val in STOCK:
        if name in PINNED:
            continue
        base = ATOMIC_BASE.get(name, name)
        if base in seen_bases:
            continue
        seen_bases.add(base)
        if val < HAVE_ARGUMENT:
            noarg_units.append(base)
        else:
            arg_units.append(base)

    # 构建可用槽位（连续的空位序列）
    def find_slots(pool_start, pool_end, pinned_vals):
        """在 [pool_start, pool_end) 中找连续的空槽，返回 list of (start, size) 区间。"""
        # 简化：直接生成所有可用位置列表，然后贪心分配单元
        all_positions = [v for v in range(pool_start, pool_end)
                         if v not in pinned_vals]
        return all_positions

    pinned_vals = {STOCK_MAP[n] for n in PINNED}
    noarg_pinned = {v for v in pinned_vals if v < HAVE_ARGUMENT}
    arg_pinned = {v for v in pinned_vals if v >= HAVE_ARGUMENT}

    rng.shuffle(noarg_units)
    rng.shuffle(arg_units)

    new = {}

    # 无参池
    pos = 0
    for base in noarg_units:
        members = _unit_members(base)
        size = len(members)
        # 找到 size 个连续槽位
        while pos + size <= HAVE_ARGUMENT:
            # 检查 pos..pos+size-1 是否都不在 pinned 中
            ok = True
            for k in range(size):
                if (pos + k) in noarg_pinned:
                    ok = False
                    break
            if ok:
                break
            pos += 1
        for j, mname in enumerate(members):
            new[mname] = pos + j
        pos += size

    # 带参池
    pos = HAVE_ARGUMENT
    for base in arg_units:
        members = _unit_members(base)
        size = len(members)
        while pos + size <= 256:
            ok = True
            for k in range(size):
                if (pos + k) in arg_pinned:
                    ok = False
                    break
            if ok:
                break
            pos += 1
        for j, mname in enumerate(members):
            new[mname] = pos + j
        pos += size

    # 固定 opcode
    for n in PINNED:
        new[n] = STOCK_MAP[n]

    return new


def build_reverse_mapping():
    """在每个可交换组内反转编号顺序；原子单元保持内部顺序。"""
    new = {}
    for group in STOCK_GROUPS:
        # 将组内的项按"单元"分组（原子单元作为一个整体）
        units = []  # list of (base_name, [members], base_val)
        seen_bases = set()
        for name, val in group:
            if name in PINNED:
                continue
            base = ATOMIC_BASE.get(name, name)
            if base in seen_bases:
                continue
            seen_bases.add(base)
            members = _unit_members(base)
            units.append((base, members, val))

        # 反转单元顺序，但单元内部保持原顺序
        reversed_units = list(reversed(units))

        # 重新分配位置：保持组内原有总槽位数和起始位置
        # 简化：按原组的第一个值和最后一个值的区间，
        # 从左到右依次放入反转后的单元
        orig_first_val = group[0][1]
        # 找到组内原值的范围
        orig_vals = [v for _, v in group]
        orig_min = min(orig_vals)
        orig_max = max(orig_vals)

        pos = orig_min
        for base, members, _ in reversed_units:
            size = len(members)
            # 跳过间隙（保留原有间隙模式不现实，我们用连续填充）
            for j, mname in enumerate(members):
                new[mname] = pos + j
            pos += size

    # 固定 opcode
    for n in PINNED:
        new[n] = STOCK_MAP[n]

    return new


def validate(mapping):
    names = {n for n, _ in STOCK}
    assert set(mapping) == names, "mapping 缺少/多出 opcode"
    vals = list(mapping.values())
    assert len(vals) == len(set(vals)), "opcode 编号出现重复"
    for n, stock in STOCK:
        v = mapping[n]
        assert 0 <= v < 256, f"{n}: 值 {v} 越界"
        if n in PINNED:
            assert v == stock, f"{n}: 固定 opcode 被改动 ({v} != {stock})"
        elif stock < HAVE_ARGUMENT:
            assert v < HAVE_ARGUMENT, f"{n}: 无参 opcode 被放到带参区 ({v})"
        else:
            assert v >= HAVE_ARGUMENT, f"{n}: 带参 opcode 被放到无参区 ({v})"
    # 验证原子单元连续性
    for unit in ATOMIC_UNITS:
        base_val = mapping[unit[0]]
        for j, name in enumerate(unit):
            assert mapping[name] == base_val + j, (
                f"原子单元 {unit[0]} 不连续: {name} = {mapping[name]}, "
                f"预期 {base_val + j}")
    return True


# ---------------------------------------------------------------------------
# frozen.c 处理
# ---------------------------------------------------------------------------

# 清空冻结模块，避免旧字节码与新 opcode 冲突。
# 保留空的数组结构，只把 M___hello__ 替换为零长度占位。
FROZEN_DUMMY = """
/* Dummy frozen modules initializer
   (scramble_27_opcodes: frozen bytecode cleared after opcode remapping) */

#include "Python.h"

static struct _frozen _PyImport_FrozenModules[] = {
    {0, 0, 0} /* sentinel */
};

struct _frozen *PyImport_FrozenModules = _PyImport_FrozenModules;
"""


def update_frozen_c(path=FROZEN_C):
    with open(path, "r", encoding="utf-8") as f:
        old = f.read()
    if old.strip() == FROZEN_DUMMY.strip():
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(FROZEN_DUMMY)
    return True


def restore_frozen_c(path=FROZEN_C):
    # 官方原始版本
    original = """
/* Dummy frozen modules initializer */

#include "Python.h"

/* In order to test the support for frozen modules, by default we
   define a single frozen module, __hello__.  Loading it will print
   some famous words... */

/* To regenerate this data after the bytecode or marshal format has changed,
   go to ../Tools/freeze/ and freeze the hello.py file; then copy and paste
   the appropriate bytes from M___main__.c. */

static unsigned char M___hello__[] = {
    99,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,115,9,0,0,0,100,0,0,71,72,100,1,0,83,40,
    2,0,0,0,115,14,0,0,0,72,101,108,108,111,32,119,
    111,114,108,100,46,46,46,78,40,0,0,0,0,40,0,0,
    0,0,40,0,0,0,0,40,0,0,0,0,115,8,0,0,
    0,104,101,108,108,111,46,112,121,115,1,0,0,0,63,1,
    0,0,0,115,0,0,0,0,
};

#define SIZE (int)sizeof(M___hello__)

static struct _frozen _PyImport_FrozenModules[] = {
    /* Test module */
    {"__hello__", M___hello__, SIZE},
    /* Test package (negative size indicates package-ness) */
    {"__phello__", M___hello__, -SIZE},
    {"__phello__.spam", M___hello__, SIZE},
    {0, 0, 0} /* sentinel */
};

/* Embedding apps may change this pointer to point to their favorite
   collection of frozen modules: */

struct _frozen *PyImport_FrozenModules = _PyImport_FrozenModules;
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(original)


# ---------------------------------------------------------------------------
# import.c MAGIC 号处理
# ---------------------------------------------------------------------------

MAGIC_RE = re.compile(r"^#define MAGIC \((?P<val>\d+)\s*\|")

def update_magic(path=IMPORT_C, offset=1):
    """修改 MAGIC 数值（增加 offset），使旧的 .pyc 文件失效。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    changed = False
    for i, line in enumerate(lines):
        m = MAGIC_RE.match(line)
        if m:
            old_val = int(m.group("val"))
            new_val = old_val + offset
            lines[i] = line.replace(str(old_val), str(new_val), 1)
            changed = True
            break
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    return changed


def restore_magic(path=IMPORT_C):
    """恢复官方原始 MAGIC = 62211。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    changed = False
    for i, line in enumerate(lines):
        m = MAGIC_RE.match(line)
        if m:
            old_val = int(m.group("val"))
            if old_val != 62211:
                lines[i] = line.replace(str(old_val), "62211", 1)
                changed = True
            break
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    return changed


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run(seed=None, reverse=False, restore=False, check=False, quiet=False):
    """主入口：返回 (mapping, changed)。"""
    lines, decls, has_lines, ext_line = parse_opcode_py()
    h_lines, h_defs, h_also = parse_opcode_h()

    if check:
        current = {m.group("name"): int(m.group("num")) for _, m in decls}
        ok = current == STOCK_MAP
        if ok:
            print("Lib/opcode.py 当前为官方原始编号 (OK)")
        else:
            diff = {n: (current.get(n), STOCK_MAP.get(n))
                    for n in set(current) | set(STOCK_MAP)
                    if current.get(n) != STOCK_MAP.get(n)}
            print("Lib/opcode.py 已被修改:", diff)
        return STOCK_MAP, False

    if restore:
        mapping = dict(STOCK_MAP)
        mode = "restore"
        # 官方原版已知正确，不做原子单元连续性校验
        # （CALL_FUNCTION 家族在原版中不连续，但满足 &3 约束）
    else:
        if seed is not None:
            mapping = build_seed_mapping(seed)
            mode = f"seed={seed}"
        else:
            mapping = build_reverse_mapping()
            mode = "reverse"
        validate(mapping)

    # 写 Lib/opcode.py
    new_lines, changed_py = apply_mapping_to_opcode_py(
        lines, decls, has_lines, ext_line, mapping)
    if changed_py:
        with open(OPCODE_PY, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"[scramble] 已更新 Lib/opcode.py (mode: {mode})")
    else:
        print(f"[scramble] Lib/opcode.py 无需改动 (mode: {mode})")

    # 写 Include/opcode.h
    new_h_lines, changed_h = apply_mapping_to_opcode_h(
        h_lines, h_defs, h_also, mapping)
    if changed_h:
        with open(OPCODE_H, "w", encoding="utf-8") as f:
            f.writelines(new_h_lines)
        print(f"[scramble] 已更新 Include/opcode.h (mode: {mode})")
    else:
        print(f"[scramble] Include/opcode.h 无需改动 (mode: {mode})")

    # 处理 frozen.c
    if restore:
        restore_frozen_c()
        print("[scramble] 已恢复 Python/frozen.c 为官方原始内容")
    else:
        if update_frozen_c():
            print("[scramble] 已清空 Python/frozen.c 中的冻结字节码")

    # 处理 MAGIC
    if restore:
        if restore_magic():
            print("[scramble] 已恢复 Python/import.c 中的 MAGIC 号")
    else:
        if update_magic(offset=1):
            print("[scramble] 已修改 Python/import.c 中的 MAGIC 号 (+1)")

    if not quiet:
        print(f"[scramble] {'恢复' if restore else '打乱'}了 {len(mapping)} 个 opcode:")
        for name, stock in sorted(STOCK, key=lambda kv: kv[1]):
            tag = ""
            if name in ATOMIC_SET:
                if ATOMIC_BASE[name] == name:
                    tag = "  (atomic unit)"
                else:
                    tag = "  (atomic member)"
            print(f"    {name:<32} {stock:>3} -> {mapping[name]:>3}{tag}")
    return mapping, changed_py or changed_h


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="打乱 CPython 2.7.3 的 opcode 编号 (Lib/opcode.py + Include/opcode.h)。")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--seed", type=int, metavar="N",
                   help="用随机数种子 N 打乱(无参/带参两个可交换池内各自随机排列)")
    g.add_argument("--reverse", action="store_true",
                   help="在每个可交换组内反转编号顺序(默认行为)")
    g.add_argument("--restore", action="store_true",
                   help="恢复为官方原始编号")
    g.add_argument("--check", action="store_true",
                   help="仅校验当前是否为官方原始编号")
    ap.add_argument("--quiet", action="store_true", help="不打印映射表")
    args = ap.parse_args(argv)

    if args.check:
        run(check=True, quiet=args.quiet)
    elif args.restore:
        run(restore=True, quiet=args.quiet)
    elif args.seed is not None:
        run(seed=args.seed, quiet=args.quiet)
    else:
        run(reverse=True, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
