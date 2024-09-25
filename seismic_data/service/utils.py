def is_in_enum(item, enum_class):
    return item in (member.value for member in enum_class)