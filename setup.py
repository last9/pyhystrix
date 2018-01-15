#!/usr/bin/env python

import os
import setuptools
from version import __version__


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(BASE_DIR, 'version.py')
README_FILE = os.path.join(BASE_DIR, "README.md")


# Get the long description from the README file
with open(README_FILE) as f:
    long_description = f.read()


dependencies = [
    "certifi == 2017.4.17",
    "chardet == 3.0.4",
    "httmock == 1.2.6",
    "idna == 2.5",
    "requests == 2.18.1",
    "urllib3 == 1.21.1"
]


setuptools.setup(
    name="pyhystrix",
    description="",
    long_description=long_description,
    author="Mohan Dutt",
    author_email="mohan@oogway.in",
    url="https://github.com/oogway/pyhystrix",
    version=__version__,
    py_modules=['pyhystrix', 'circuit_breaker', 'config', 'version'],
    include_package_data=True,
    install_requires=dependencies,
    test_suite="tests"
)
