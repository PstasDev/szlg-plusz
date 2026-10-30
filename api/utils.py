# HUN Grammar Utilities

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
    if is_vowel(string[0]):
        return "AZ" if uppercase else "az"
    return "A" if uppercase else "a"