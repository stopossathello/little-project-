# -*- coding: utf-8 -*-
"""把 Colab 筆記本 (.ipynb) 的程式碼 cell 抽成一份 .py, 給「直接執行」模式用。

用法: python nb_to_py.py 策略C.ipynb > strategy.py
略過: %pip 與 ! 開頭的指令、單獨一行的 display(...)、Position.from_report 下單 cell
"""
import json
import sys

SKIP_CELL = ('order_executor', 'Position.from_report')


def convert(path):
    with open(path, encoding='utf-8') as f:
        nb = json.load(f)
    cells = []
    for cell in nb.get('cells', []):
        if cell.get('cell_type') != 'code':
            continue
        src = cell.get('source', '')
        src = ''.join(src) if isinstance(src, list) else src
        if any(k in src for k in SKIP_CELL):
            continue
        lines = [l for l in src.splitlines()
                 if not l.lstrip().startswith(('%', '!')) and not l.strip().startswith('display(')]
        if any(l.strip() for l in lines):
            cells.append('\n'.join(lines))
    return '\n\n'.join(cells) + '\n'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('用法: python nb_to_py.py 筆記本.ipynb > strategy.py')
    sys.stdout.write(convert(sys.argv[1]))
