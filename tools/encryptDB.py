#! /usr/bin/python

from Tardis import Defaults, Util, TardisDB, TardisCrypto, CacheDir, librsync, Regenerator
import sqlite3
import argparse, logging
import os.path
import os
import sys
import base64
import hashlib
import sys

logger = None

def encryptFilenames(db, crypto):
    systemencoding = sys.getfilesystemencoding()
    conn = db.conn
    c = conn.cursor()
    c2 = conn.cursor()
    names = 0
    try:
        r = c.execute("SELECT Name, NameID FROM Names")
        while True:
            row = r.fetchone()
            if row is None:
                break
            (name, nameid) = row
            newname = crypto.encryptFilename(name.decode(systemencoding, 'replace'))
            c2.execute('UPDATE Names SET Name = ? WHERE NameID = ?', (newname, nameid))
            names = names + 1
        conn.commit()
        logger.info("Encrypted %d names", names)
    except Exception as e:
        logger.error("Caught exception encrypting filename %s: %s", name, str(e))
        conn.rollback()

def encryptFile(checksum, cacheDir, cipher, iv, pad, hmac, nameHmac, output = None):
    f = cacheDir.open(checksum, 'rb')
    if output == None:
        output = checksum + '.enc'
    o = cacheDir.open(output, 'wb')
    o.write(iv)
    nb = len(iv)
    hmac.update(iv)
    for chunk, eof in Util._chunks(f, 64 * 1024):
        if eof:
            chunk = pad(chunk)
        ochunk = cipher.encrypt(chunk)
        o.write(ochunk)
        nb = nb + len(ochunk)
        hmac.update(ochunk)
    ochunk = hmac.digest()
    o.write(ochunk)
    nb = nb + len(ochunk)
    o.close()
    f.close()

    return nb

def generateFullFileInfo(checksum, regenerator, cacheDir, nameMac, signature=True, basis=None):
    i = regenerator.recoverChecksum(checksum, basisFile=basis)
    sig = None
    logger.debug("    Generating HMAC for %s.  Generating signature: %s", checksum, str(signature))
    if signature:
        output = cacheDir.open(checksum + ".sig", "wb+")
        sig = librsync.SignatureJob(output)

    data = i.read(16 * 1024)
    while data:
        nameMac.update(data)
        if sig:
            sig.step(data)
        data = i.read(16 * 1024)
    # Return a handle on the full file object.  Allows it to be reused in the next step
    return i

suffixes = ['','KB','MB','GB', 'TB', 'PB']

def processFile(cksInfo, regenerator, cacheDir, db, crypto, basis=None):
    try:
        conn = db.conn
        c2 = conn.cursor()
        checksum = cksInfo['checksum']
        if cksInfo['encrypted']:
            logger.info("    Skipping  %s", checksum)
            return None

        logger.info("  Processing %s (%s, %s)", checksum, Util.fmtSize(cksInfo['size'], formats = suffixes), Util.fmtSize(cksInfo['diskSize'], formats = suffixes))
        signature = not cacheDir.exists(checksum + ".sig")
        
        nameHmac = crypto.getHash()
        retFile = generateFullFileInfo(checksum, regenerator, cacheDir, nameHmac, signature, basis)
        if basis:
            basis.close()
        newCks = nameHmac.hexdigest()
        
        logger.info("    Hashed     %s => %s (%s, %s)", checksum, newCks, Util.fmtSize(cksInfo['size'], formats = suffixes), Util.fmtSize(cksInfo['diskSize'], formats = suffixes))
        
        iv = crypto.getIV()
        cipher = crypto.getContentCipher(iv)
        hmac = crypto.getHash(func=hashlib.sha512)
        fSize = encryptFile(checksum, cacheDir, cipher, iv, crypto.pad, hmac, nameHmac, output=newCks)
        logger.info("    Encrypted  %s => %s (%s)", checksum, newCks, Util.fmtSize(fSize, formats = ['','KB','MB','GB', 'TB', 'PB']))

        #cacheDir.link(checksum + '.enc', newCks, soft=False)
        #cacheDir.link(checksum + ".sig", newCks + ".sig", soft=False)
        cacheDir.move(checksum + ".sig", newCks + ".sig")
        logger.debug("    Moved sig file, updating database")

        c2.execute('UPDATE CheckSums SET Encrypted = 1, DiskSize = :size, Checksum = :newcks WHERE Checksum = :cks',
                    {"size": fSize, "newcks": newCks, "cks": checksum})
        c2.execute('UPDATE CheckSums SET Basis = :newcks WHERE Basis = :cks', {"newcks": newCks, "cks": checksum})

        logger.debug("    Ready to commit")
        conn.commit()
        logger.debug("    Commit complete, removing files")
        cacheDir.removeSuffixes(checksum, ['.meta', '.enc', '.sig', '.basis', ''])
        logger.debug("    Done with %s", checksum)
        return retFile
    except Exception as e:
        conn.rollback()
        logger.error("Unable to convert checksum: %s :: %s", checksum, e)
        logger.exception(e)
        return None

def encryptFilesAtLevel(db, crypto, cacheDir, chainlength=0):
    logger.info("Encrypting files with chainlength = %d", chainlength)
    conn = db.conn
    c = conn.cursor()
    regenerator = Regenerator.Regenerator(cacheDir, db, crypto)

    r = c.execute("SELECT Checksum, Size, Basis, Compressed FROM Checksums WHERE Encrypted = 0 AND IsFile = 1 AND ChainLength = :chainlength ORDER BY CheckSum", {"chainlength": chainlength})
    for row in r.fetchall():
        try:
            checksum = row[0]
            logger.info("Encrypting Parent %s", checksum)
            chain = db.getChecksumInfoChain(checksum)
            bFile = None
            while chain:
                cksInfo = chain.pop()
                bFile = processFile(cksInfo, regenerator, cacheDir, db, crypto, bFile)
        except Exception as e:
            logger.error("Error processing checksum: %s", checksum)
            logger.exception(e)
            #raise e

def encryptFiles(db, crypto, cacheDir):
    conn = db.conn
    r = conn.execute("SELECT MAX(ChainLength) FROM CheckSums")
    z = r.fetchone()[0]
    for level in range(z, -1, -1):
        encryptFilesAtLevel(db, crypto, cacheDir, level)


def generateDirHashes(db, crypto, cacheDir):
    conn = db.conn
    z = conn.cursor()
    r = conn.execute("SELECT Inode, Device, LastSet, Names.name, Checksums.ChecksumId, Checksum "
                     "FROM Files "
                     "JOIN Names ON Names.NameId = Files.NameID "
                     "JOIN Checksums ON Files.ChecksumId = Checksums.ChecksumId "
                     "WHERE Dir = 1 "
                     "ORDER BY Checksum")
    lastHash = None
    batch = r.fetchmany()
    while batch:
        for row in batch:
            inode = row['Inode']
            device = row['Device']
            last = row['LastSet']
            oldHash = row['Checksum']
            cksId = row['ChecksumId']
            files = db.readDirectory((inode, device), last)

            if oldHash == lastHash:
                continue
            lastHash = oldHash

            logger.debug("Rehashing directory %s (%d, %d)@%d: %s(%d)", crypto.decryptFilename(row['Name']),inode, device, last, oldHash, cksId)
            #logger.debug("    Directory contents: %s", str(files))
            (newHash, newSize) = Util.hashDir(crypto, files, True, True)
            logger.info("Rehashed %s => %s.  %d files", oldHash, newHash, newSize)
            try:
                if newHash != oldHash:
                    z.execute("UPDATE Checksums SET Checksum = :newHash WHERE ChecksumId = :id", {"newHash": newHash, "id": cksId})
            except Exception:
                pass
        batch = r.fetchmany()

def generateSignatures(db, cacheDir):
    c = db.conn.cursor()
    r = c.execute("SELECT Checksum FROM Checksums")
    regenerator = Regenerator.Regenerator(cacheDir, db, crypto)
    for row in r.fetchall():
        checksum = row[0]
        sigfile = checksum + '.sig'
        if not cacheDir.exists(sigfile):
            logger.info("Generating signature for {}".format(checksum))
            makeSig(checksum, regenerator, cacheDir)

def generateMetadata(db, cacheDir):
    conn = db.conn
    c = conn.cursor()
    r = c.execute("SELECT Checksum, Size, Compressed, Encrypted, DiskSize, Basis FROM Checksums WHERE IsFile = 1 ORDER BY CheckSum")
    batch = r.fetchmany(4096)
    while batch:
        for row in batch:
            # recordMetaData(cache, checksum, size, compressed, encrypted, disksize, basis=None, logger=None):
            Util.recordMetaData(cacheDir, row[0], row[1], row[2], row[3], row[4], basis=row[5], logger=logger)
        batch = r.fetchmany(4096)

def processArgs():
    parser = argparse.ArgumentParser(description='Encrypt the database')
    parser.add_argument('--database', '-D', dest='database', default=Defaults.getDefault('TARDIS_DB'),      help="Database to use.  Default: %(default)s")
    parser.add_argument('--client', '-C',   dest='client',   default=Defaults.getDefault('TARDIS_CLIENT'),  help="Client to list on.  Default: %(default)s")
    parser.add_argument('--dbname',         dest='dbname',   default=Defaults.getDefault('TARDIS_DBNAME'),  help="Name of the database file. Default: %(default)s")

    parser.add_argument('--filenames',      dest='filenames', action='store_true', default=False,       help='Encrypt filenames. Default=%(default)s')
    parser.add_argument('--files',          dest='files',     action='store_true', default=False,       help='Encrypt files. Default=%(default)s')
    parser.add_argument('--dirhashes',      dest='dirhash',   action='store_true', default=False,       help='Generate directory hashes.  Default=%(default)s')
    parser.add_argument('--meta',           dest='meta',      action='store_true', default=False,       help='Generate metadata files.  Default=%(default)s')
    #parser.add_argument('--signatures',     dest='sigs',      action='store_true', default=False,       help='Generate signatures. Default=%(default)s')

    passgroup= parser.add_argument_group("Password/Encryption specification options")
    pwgroup = passgroup.add_mutually_exclusive_group(required=True)
    pwgroup.add_argument('--password', '-P',dest='password', default=None, nargs='?', const=True,       help='Encrypt files with this password')
    pwgroup.add_argument('--password-file', dest='passwordfile', default=None,                          help='Read password from file')
    pwgroup.add_argument('--password-url',  dest='passwordurl', default=None,                           help='Retrieve password from the specified URL')
    pwgroup.add_argument('--password-prog', dest='passwordprog', default=None,                          help='Use the specified command to generate the password on stdout')

    return parser.parse_args()

def main():
    global logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('')
    args = processArgs()
    password = Util.getPassword(args.password, args.passwordfile, args.passwordurl, args.passwordprog)

    crypto = TardisCrypto.TardisCrypto(password, args.client)
    token = crypto.createToken()

    #logger.info("Created token: %s", token)
    path = os.path.join(args.database, args.client, args.dbname)
    db = TardisDB.TardisDB(path, token=token, backup=False)
    (f, c) = db.getKeys()
    crypto.setKeys(f, c)

    cacheDir = CacheDir.CacheDir(os.path.join(args.database, args.client))

    #if args.sigs:
    #    generateSignatures(db, cacheDir)
    if args.filenames:
        encryptFilenames(db, crypto)
    if args.files:
        encryptFiles(db, crypto, cacheDir)
    if args.dirhash:
        generateDirHashes(db, crypto, cacheDir)
    if args.meta:
        generateMetadata(db, cacheDir)

if __name__ == "__main__":
    main()
