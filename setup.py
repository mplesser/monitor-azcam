from setuptools import setup, find_packages


with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="azcam-monitor",
    version="20.1",
    description="azcam processes monitor and control app",
    long_description=long_description,
    author="Michael Lesser",
    author_email="mlesser@arizona.edu",
    keywords="ccd imaging astronomy observation observatory",
    packages=find_packages(),
    zip_safe=False,
    install_requires=["azcam", "flask"],
)
