from setuptools import setup, find_packages

setup(
    name="gitback",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "rich",
    ],
    entry_points={
        "console_scripts": [
            "gitback=gitback.main:main",
        ],
    },
    author="pheonix14 & rayzien",
    description="GitHub to GitLab Migration & Backup Tool",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/rayzien/GITBACK",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)
