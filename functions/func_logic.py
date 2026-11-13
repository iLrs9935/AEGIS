# functions/func_logic.py


def set_context_value(context, key, value):
    """写入全局状态"""
    if key.strip():
        context[key.strip()] = value


def get_context_value(context, key, default=None):
    """读取全局状态"""
    return context.get(key.strip(), default)


def check_logic_and(context, keys):
    """多条件【与】逻辑 (必须全部为 True 才返回 True)"""
    valid_keys = [k.strip() for k in keys if k.strip()]
    if not valid_keys:
        return False
    return all(context.get(k) is True for k in valid_keys)


def check_logic_or(context, keys):
    """多条件【或】逻辑 (只要有一个为 True 就返回 True)"""
    valid_keys = [k.strip() for k in keys if k.strip()]
    if not valid_keys:
        return False
    return any(context.get(k) is True for k in valid_keys)
