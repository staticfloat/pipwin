# -*- coding: utf-8 -*-

import pip
import requests
from robobrowser import RoboBrowser
from os.path import expanduser, join, isfile, exists
import os
import json
import struct
from sys import version_info
from itertools import product
import pyprind
import six
import js2py

# Python 2.X 3.X input
try:
    input = raw_input
except NameError:
    pass

MAIN_URL = "http://www.lfd.uci.edu/~gohlke/pythonlibs/"

HEADER = {
    "Host": "www.lfd.uci.edu",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/48.0.2552.0 Safari/537.3",
    "DNT": "1",
    "Accept-Encoding": "gzip, deflate, sdch",
    "Accept-Language": "en-US,en;q=0.8",
    "Referer": "http://www.lfd.uci.edu/~gohlke/pythonlibs/"
}

def build_cache():
    """
    Get current data from the website http://www.lfd.uci.edu/~gohlke/pythonlibs/

    Returns
    -------
    Dictionary containing package details
    """

    data = {}

    soup = RoboBrowser()
    soup.open(MAIN_URL)

    # We mock out a little javascript environment within which to run Gohlke's obfuscation code
    context = js2py.EvalJs()
    context.execute("""
    top = {location: {href: ''}};
    location = {href: ''};
    function setTimeout(f, t) {
        f();
    };
    """)

    # We grab Gohlke's code and evaluate it within py2js
    context.execute(soup.find("script").text)

    links = soup.find(class_="pylibs").find_all("a")
    for link in links:
        if link.get("onclick") is not None:
            # Evaluate the obfuscation javascript, store the result (squirreled away within location.href) into url
            context.execute(link.get("onclick").split("javascript:")[-1])
            url = MAIN_URL + context.location.href

            # Details = [package, version, pyversion, --, arch]
            details = url.split("/")[-1].split("-")
            pkg = details[0].lower().replace("_", "-")

            # Not using EXEs and ZIPs
            if len(details) != 5:
                continue
            # arch = win32 / win_amd64 / any
            arch = details[4]
            arch = arch.split(".")[0]
            # ver = cpXX / pyX / pyXXx
            pkg_ver = details[1]
            py_ver = details[2]

            py_ver_key = py_ver + "-" + arch

            if pkg in data.keys():
                if py_ver_key in data[pkg].keys():
                    data[pkg][py_ver_key].update({pkg_ver: url})
                else:
                    data[pkg][py_ver_key] = {pkg_ver: url}
            else:
                data[pkg] = {py_ver_key: {pkg_ver: url}}

    return data


def filter_packages(data):
    """
    Filter packages based on your current system
    """

    sys_data = {}

    # Check lists
    verlist = []
    archlist = []
    ver = version_info[:2]
    verlist.append("cp" + str(ver[0]) + str(ver[1]))
    verlist.append("py" + str(ver[0]))
    verlist.append("py" + str(ver[0]) + str(ver[1]))
    verlist.append("py2.py3")

    archlist.append("any")
    if (struct.calcsize("P") * 8) == 32:
        archlist.append("win32")
    elif (struct.calcsize("P") * 8) == 64:
        archlist.append("win_amd64")

    checklist = list(map("-".join, list(product(verlist, archlist))))

    for key in data.keys():
        presence = list(map(lambda x: x in data[key].keys(), checklist))
        try:
            id = presence.index(True)
        except ValueError:
            # Version not found
            continue
        sys_data[key] = data[key][checklist[id]]

    return sys_data


class PipwinCache(object):
    """
    Pipwin cache class
    """

    def __init__(self, refresh=False):
        """
        Search if cache file is there in HOME.
        If not, build one.

        Parameters
        ----------
        refresh: boolean
            If True, rebuilds the cache.
        """

        home_dir = expanduser("~")
        self.cache_file = join(home_dir, ".pipwin")

        if isfile(self.cache_file) and not refresh:
            with open(self.cache_file) as fp:
                cache_dump = fp.read()
            self.data = json.loads(cache_dump)
        else:
            print("Building cache. Hang on . . .")
            self.data = build_cache()

            with open(self.cache_file, "w") as fp:
                fp.write(json.dumps(self.data,
                                    sort_keys=True,
                                    indent=4,
                                    separators=(",", ": ")))

            print("Done")

        if not refresh:
            # Create a package list for the system
            self.sys_data = filter_packages(self.data)

    def print_list(self):
        """
        Print the list of packages available for system
        """

        print("# Listing packages available for your system\n")
        for package in self.sys_data.keys():
            print(package)
        print("")

    def search(self, requirement):
        """
        Search for a package

        Returns
        -------
        exact_match : boolean
            True if exact match is found
        matches : list
            List of matches. Is a string if exact_match is True.
        """

        if requirement.name in self.sys_data.keys():
            return [True, requirement.name]

        # find all packages that contain our search term within them
        found = [pack for pack in self.sys_data.keys() if requirement.name in pack]
        return [False, found]

    def _get_url(self, requirement):
        versions = list(requirement.specifier.filter(self.sys_data[requirement.name].keys()))
        if not versions:
            raise ValueError("Could not satisfy requirement %s"%(str(requirement)))
        return self.sys_data[requirement.name][max(versions)]

    def _get_pipwin_dir(self):
        home_dir = expanduser("~")
        pipwin_dir = join(home_dir, "pipwin")
        if not exists(pipwin_dir):
            os.makedirs(pipwin_dir)
        return pipwin_dir

    def _get_progress_bar(self, length, chunk):
        bar = pyprind.ProgBar(int(length) / chunk)
        if int(length) < chunk:
            return None
        return bar

    def _download(self, requirement):
        url = self._get_url(requirement)
        wheel_name = url.split("/")[-1]
        print("Downloading package . . .")
        print(url)
        print(wheel_name)

        wheel_file = join(self._get_pipwin_dir(), wheel_name)

        res = requests.get(url, headers=HEADER, stream=True)
        length = res.headers.get("content-length")
        chunk = 1024

        bar = self._get_progress_bar(length, chunk)

        with open(wheel_file, "wb") as wheel_handle:
            for block in res.iter_content(chunk_size=chunk):
                wheel_handle.write(block)
                wheel_handle.flush()
                if bar is not None:
                    bar.update()
        return wheel_file

    def download(self, requirement):
        return self._download(requirement)

    def install(self, requirement):
        """
        Install a package
        """
        wheel_file = self.download(requirement)
        pip.main(["install", wheel_file])

        os.remove(wheel_file)

    def uninstall(self, requirement):
        """
        Uninstall a package
        """

        pip.main(["uninstall", self.sys_data[requirement.name]])


def refresh():
    """
    Rebuild the cache
    """

    PipwinCache(refresh=True)
