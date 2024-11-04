import toml

def generate_requirements(pyproject_file_path, poetry_lock_file_path, requirements_file_path):
    # Load pyproject.toml
    pyproject = toml.load(pyproject_file_path)
    # Get the main dependencies from pyproject.toml (excluding 'python')
    main_dependencies = pyproject.get('tool', {}).get('poetry', {}).get('dependencies', {})
    main_dependencies.pop('python', None)

    # Load poetry.lock
    with open(poetry_lock_file_path, 'r') as f:
        poetry_lock = toml.load(f)

    # Get package details from poetry.lock
    resolved_versions = {}
    for package in poetry_lock.get('package', []):
        name = package['name']
        version = package['version']
        if name in main_dependencies:
            resolved_versions[name] = version

    # Write to requirements.txt
    with open(requirements_file_path, 'w') as f:
        for package, version in resolved_versions.items():
            f.write(f"{package}=={version}\n")

# Generate requirements.txt using pyproject.toml and poetry.lock
generate_requirements('pyproject.toml', 'poetry.lock', 'requirements.txt')
