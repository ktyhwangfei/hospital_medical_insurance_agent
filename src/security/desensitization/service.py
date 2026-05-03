def mask_name(name: str) -> str:
    return name[0] + '**' if name else ''
