
# backend/units.py

def parse_size(size_str: str, binary: bool = True) -> int:
    """
    Parses a human-readable size string (e.g., "10GB", "2.5GiB") into bytes.
    Supports K, M, G, T suffixes, case-insensitive.
    If binary is True, uses 1024-based (KiB, MiB, etc.); otherwise, 1000-based (KB, MB, etc.).
    """
    if not isinstance(size_str, str):
        raise TypeError("size_str must be a string")

    size_str = size_str.strip()
    if not size_str:
        return 0

    # Define the base for calculations
    base = 1024 if binary else 1000

    # Regular expression to parse the size string
    import re
    match = re.match(r"([0-9.]+)([KMGT]?)(iB|B)?", size_str, re.IGNORECASE)

    if not match:
        raise ValueError(f"Invalid size string format: {size_str}")

    value, suffix, unit = match.groups()
    value = float(value)

    if suffix:
        suffix = suffix.upper()
        if suffix == 'K':
            value *= base
        elif suffix == 'M':
            value *= base ** 2
        elif suffix == 'G':
            value *= base ** 3
        elif suffix == 'T':
            value *= base ** 4
        # Additional suffixes can be added here if needed

    return int(value)

def format_size(size_bytes: int, binary: bool = True, precision: int = 1) -> str:
    """
    Formats a size in bytes into a human-readable string (e.g., "10 GB", "2.5 GiB").
    If binary is True, uses 1024-based (KiB, MiB, etc.); otherwise, 1000-based (KB, MB, etc.).
    """
    if not isinstance(size_bytes, (int, float)):
        raise TypeError("size_bytes must be an integer or float")
    if size_bytes < 0:
        return f"-{format_size(abs(size_bytes), binary, precision)}"

    if size_bytes == 0:
        return "0 B"

    base = 1024 if binary else 1000
    suffixes_binary = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
    suffixes_decimal = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    suffixes = suffixes_binary if binary else suffixes_decimal

    i = 0
    while size_bytes >= base and i < len(suffixes) - 1:
        size_bytes /= base
        i += 1

    return f"{size_bytes:.{precision}f} {suffixes[i]}"
