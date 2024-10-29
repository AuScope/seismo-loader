from datetime import datetime, date


def is_in_enum(item, enum_class):
    return item in (member.value for member in enum_class)

def convert_to_date(value):
    """Convert a string or other value to a date object, handling different formats."""
    if isinstance(value, date):
        return value
    elif isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                st.error(f"Invalid date format: {value}. Expected ISO format 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'.")
                return date.today()  
    else:
        return date.today() 