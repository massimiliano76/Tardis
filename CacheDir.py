# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Tardis: A Backup System
# Copyright 2013-2014, Eric Koldinger, All Rights Reserved.
# kolding@washington.edu
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import os
import os.path
import socket
import logging

class CacheDir:
    def __init__(self, root, parts=2, partsize=2):
        logger.debug("Creating CacheDir: path={}, parts={}, partsize={})".format(root, parts, partsize))
        self.root = os.path.abspath(root)
        self.parts = parts
        self.partsize = partsize
        try:
            os.makedirs(self.root)
        except OSError, error:
            pass

    def comps(self, name):
        return [name[(i * self.partsize):((i + 1) * self.partsize)] for i in range(0, self.parts)]

    def dir(self, name):
        return reduce(os.path.join, self.comps(name), self.root)

    def path(self, name):
        return os.path.join(self.dir(name), name)

    def exists(self, name):
        return os.path.exists(self.path(name))

    def mkdir(self, name):
        dir = self.dir(name)
        if not os.path.isdir(dir):
            os.makedirs(dir)

    def open(self, name, mode):
        if mode.startswith("w"):
            dir = self.dir(name)
            if not os.path.isdir(dir):
                os.makedirs(dir)
        return open(self.path(name), mode)

    def remove(self, name):
        try:
            os.remove(self.path(name))
            return True
        except OSError:
            return False

logger = logging.getLogger("CacheDir")

if __name__ == "__main__":
    test = "abcdefghijklmnop"
    path = os.path.join("cache", socket.gethostname())
    c = CacheDir(path, 4, 2)
    print c.comps(test)
    print c.dir(test)
    print c.path(test)
    print c.exists(test)

    try:
        c.open(test, "r")
    except IOError as ex:
        print "Caught IOError"

    with c.open(test, "w") as fd:
        fd.write("I'm henry the 8'th I am\n")
        fd.write("Henry the 8th, I am I am\n")

    with c.open(test, "r") as fd:
        for line in fd:
            print line,
    print c.exists(test)

