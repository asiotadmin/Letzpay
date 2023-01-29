from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in letzpay_integration/__init__.py
from letzpay_integration import __version__ as version

setup(
	name="letzpay_integration",
	version=version,
	description="Letzpay Integration",
	author="Stya",
	author_email="satyabrata12017@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
