# HUN Grammar Utilities


class Colors:
    """Section and role palettes for generated DiceBear avatars."""

    CLASS_COLORS = {
        "A": "#66bb6a",
        "B": "#ffca28",
        "C": "#ba68c8",
        "D": "#ef5350",
        "E": "#bdbdbd",
        "F": "#5c6bc0",
    }
    CLASS_INK_COLORS = {
        "A": "345945",
        "B": "5b4e30",
        "C": "5e3b87",
        "D": "7b373f",
        "E": "3b3b42",
        "F": "33477f",
    }
    TEACHER_COLORS = ("d0edec", "345757")
    OTHER_COLORS = ("ede3e9", "733662")

    @staticmethod
    def get_color(classLetter):
        """Return the SZLG+ section color, or None for an unknown section."""
        if not classLetter:
            return None
        return Colors.CLASS_COLORS.get(str(classLetter).strip().upper())

    @classmethod
    def get_dicebear_colors(
        cls, *, class_letter=None, is_teacher=False, is_student=False
    ):
        """Choose one stable DiceBear background/ink pair for a user's role."""
        if is_teacher:
            return cls.TEACHER_COLORS

        section = str(class_letter or "").strip().upper()
        color = cls.get_color(section)
        if is_student and color:
            return color.lstrip("#"), cls.CLASS_INK_COLORS[section]

        return cls.OTHER_COLORS


number_pronunciation_map = [
    (1, "egy"),
    (2, "kettő"),
    (3, "három"),
    (4, "négy"),
    (5, "öt"),
    (6, "hat"),
    (7, "hét"),
    (8, "nyolc"),
    (9, "kilenc"),
    (0, "nulla"),
    (10, "tíz"),
    (20, "húsz"),
    (30, "harminc"),
    (40, "negyven"),
    (50, "ötven"),
    (60, "hatvan"),
    (70, "hetven"),
    (80, "nyolcvan"),
    (90, "kilencven"),
    (100, "száz"),
    (1000, "ezer"),
    (1000000, "millió"),
    (1000000000, "milliárd"),
    (1000000000000, "billió"),
    (1000000000000000, "trillió"),
    (1000000000000000000, "kvadrillió"),
]

def pronounce_numbers_in_string(string):
    for number, pronunciation in sorted(number_pronunciation_map, key=lambda x: -x[0]):
        string = string.replace(str(number), pronunciation)
    return string

def is_vowel(char):
    vowels = "aáeéiíoóöőuúüű"
    return char.lower() in vowels

def is_consonant(char):
    return not is_vowel(char)

def starts_with_number(string):
    if not string:
        return False
    return string[0].isdigit()

def decide_prefix_a_or_az(string, uppercase=False):
    if starts_with_number(string):
        string = pronounce_numbers_in_string(string)
    if string.startswith("SZLG"):
        return "Az" if uppercase else "az"
    if is_vowel(string[0]):
        return "Az" if uppercase else "az"
    return "A" if uppercase else "a"
