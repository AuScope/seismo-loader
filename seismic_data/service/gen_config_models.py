import configparser
from textwrap import indent

file_paths = ['example_event.cfg', 'example_continuous.cfg']

def merge_configs():
    master_config = configparser.ConfigParser()
    for path in file_paths:
        config = configparser.ConfigParser()
        config.read(path)
        for section in config.sections():
            if not master_config.has_section(section):
                master_config.add_section(section)
            for key, value in config.items(section):
                if not master_config.has_option(section, key):
                    master_config.set(section, key, value)
    return master_config


def generate_pydantic_model_from_config():

    config = merge_configs()
    classes = []
    
    # Generate class definitions based on sections
    for section in config.sections():
        class_name = ''.join(word.title() for word in section.split('_')) + 'Config'
        field_definitions = []
        for key, _ in config.items(section):
            field_type = 'str'  # Default to str, you can enhance this to infer type
            field_line = f"{key}: {field_type}"
            field_definitions.append(field_line)
        
        class_body = "\n    ".join(field_definitions)
        class_definition = f"class {class_name}(BaseModel):\n    {class_body}\n"
        classes.append(class_definition)
    
    # Combine all class definitions into a single module
    full_model = "\n".join(classes)
    model_code = f"from pydantic import BaseModel\n\n{full_model}"
    
    
    with open('config_model.py', 'w') as f:
        f.write(model_code)


if __name__ == "__main__":
    generate_pydantic_model_from_config()