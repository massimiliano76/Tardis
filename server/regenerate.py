#! /usr/bin/python

import os
import os.path
import sys
import argparse
import socket
import TardisDB
import CacheDir
import logging
import subprocess

version = "0.1"

database = "./tardisDB"

def recoverChecksum(cksum, db, cacheDir):
    (name, basis) = db.getChecksumInfo(cksum)
    if basis:
        input = recoverChecksum(basis, db, cacheDir)
        pipe = subprocess.Popen(["rdiff", "patch", "-", cacheDir.path(name)], stdin=input, stdout=subprocess.PIPE)
        return pipe.stdout
    else:
        return cacheDir.open(name, "rb")

def recoverFile(file, db, cacheDir):
    print "Recover file: " + file
    return

if __name__ == "__main__":
    parser = argparse.ArgumentParser("Regenerate a Tardis file")

    parser.add_argument("--output", "-o", dest="output", help="Output file", default=None)
    parser.add_argument("--database", help="Path to database directory", dest="database", default=database)
    parser.add_argument("--backup", "-b", help="backup set to use", dest='backup', default=None)
    parser.add_argument("--host", "-H", help="Host to process for", dest='host', default=socket.gethostname())
    parser.add_argument("--checksum", "-c", help="Use checksum instead of filename", dest='cksum', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='count', dest='verbose', help='Increase the verbosity')
    parser.add_argument('--version', action='version', version='%(prog)s ' + version, help='Show the version')
    parser.add_argument('files', nargs='*', default=None, help="List of files to regenerate")

    args = parser.parse_args()
    print args


    logger = logging.getLogger("")
    format = logging.Formatter("%(levelname)s : %(name)s : %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(format)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    baseDir = os.path.join(args.database, args.host)
    dbName = os.path.join(baseDir, "tardis.db")
    db = TardisDB.TardisDB(dbName, backup=False, prevSet=args.backup)

    cacheDir = CacheDir.CacheDir(baseDir)

    if args.output:
        output = file(args.output, "wb")
    else:
        output = sys.stdout

    for i in args.files:
        f = None
        if args.cksum:
            f = recoverChecksum(i, db, cacheDir)
        else:
            f = recoverFile(i, db, cacheDir)

        x = f.read(16 * 1024)
        while x:
            output.write(x)
            x = f.read(16 * 1024)

        f.close()
