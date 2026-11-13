# functions/func_text.py


def merge_strings(text_a: str, text_b: str, separator: str = "\n") -> str:
    """纯粹的字符串合并逻辑"""
    if text_a is None:
        text_a = ""
    if text_b is None:
        text_b = ""

    # 处理转义符
    actual_separator = separator.replace("\\n", "\n").replace("\\t", "\t")
    return f"{text_a}{actual_separator}{text_b}"


def format_simple_display(content: str) -> str:
    """极简展示格式：只打印内容本身，不带繁杂的边框"""
    if content is None:
        return "<无数据>"
    return str(content)
