
import configparser
import subprocess
import pprint
import os
from urllib.parse import urljoin
from functools import reduce
from os.path import dirname, join
from enum import Enum

pformat = pprint.PrettyPrinter(indent=4).pformat

class ConfigParser(configparser.ConfigParser):
    def __init__(self, defaults=None):
        configparser.ConfigParser.__init__(self, defaults=None)
    def optionxform(self, optionstr):
        return optionstr

class Visibility(Enum):
    Invisible = 0
    Visible = 1

def dictUpsert(t, keys, value):
    node = t
    for idx in range(0, len(keys) - 1):
        key = keys[idx]
        if not key in node:
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value

class Generator:
    def __init__(self, directoryTree):
        self.directoryTree = directoryTree
        self.permissions = {}
        self.groupDefaultPermissions = {}
        self.groups = {}
        self.repoBranches = []
        self.repoName = None
    
    def parse(self, config):
        self.repoName = config.get("repo", "name")
        branches = config.get("repo", "path").split(",")
        repoBranches = []
        for branch in branches:
            repoBranches.append(branch.strip())
        self.repoBranches = repoBranches

        print("repoName=%s, repoPath=%s" % (self.repoName, self.repoBranches))

        for group in config["groups"]:
            self.groups[group] = config["groups"][group]

            if config.has_section(group):
                pathes = list(config[group].keys())
                # sort to set parent permission first
                pathes.sort()
                for path in pathes:
                    permissions = config.get(group, path)
                    self.parseOnePermissions(group, path, permissions)
        self.parseGroupDefaultPermissions()
        # self.parseDefaultPermissions()
        # self.parseShrinkPermissions()

        print("permissions =", pformat(self.permissions))
        print("groupDefaultPermissions", pformat(self.groupDefaultPermissions))
    
    def parseOnePermissions(self, groupName, pathStr, permissionStr):
        permissionTrunk = self.parsePermissionTrunk(permissionStr)
        permission = permissionTrunk['permission']
        visibility = permissionTrunk['visibility']

        if pathStr[-1] == '*':
            path = self.directoryTree.addDirectory(pathStr[0:-1])
            dictUpsert(self.groupDefaultPermissions, [groupName, path], permission)
        else:
            path = self.directoryTree.addDirectory(pathStr)
            dictUpsert(self.permissions, [path, groupName], permission)
            if visibility == Visibility.Visible:
                self.parsePermissionVisibility(path, groupName, permission)

    def parsePermissionVisibility(self, path, groupName, permission):
        node = path
        while node:
            ancestor = node.getParent()
            if ancestor is None:
                break
            if ancestor in self.permissions:
                p = self.permissions[ancestor]
                if groupName in p:
                    break
                else:
                    p[groupName] = 'r'
            else:
                dictUpsert(self.permissions, [ancestor, groupName], 'r')
            self.parseOnePermissions(groupName, os.path.join(ancestor.toPathStr(), '*'), '')
            node = ancestor
    
    def parsePermissionTrunk(self, permission):
        t = list(map(lambda x: x.strip(), permission.split(',')))
        v = Visibility.Invisible
        if len(t) > 1 and t[1] == 'visible':
            v = Visibility.Visible
        return {
            'permission' : t[0],
            'visibility' : v,
        }

    def parseGroupDefaultPermissions(self):
        for groupName in self.groupDefaultPermissions:
            node = self.groupDefaultPermissions[groupName]
            for path in node:
                childs = path.getChilds()
                for name in childs:
                    child = childs[name]
                    if child in self.permissions:
                        if groupName in self.permissions[child]:
                            continue
                    self.parseOnePermissions(groupName, child.toPathStr(), node[path])

    # def parseDefaultPermissions(self):
    #     for path in self.permissions:
    #         self.permissions[path]["*"] = ''

    # def parseShrinkPermissions(self):
    #     for path in self.permissions:
    #         permissionsNode = self.permissions[path]
    #         toDel = []
    #         for group in permissionsNode:
    #             if group != '*' and permissionsNode[group] == '':
    #                 toDel.append(group)
    #         for group in toDel:
    #             del permissionsNode[group]
                
    def generate(self, path):
        config = configparser.ConfigParser()
        self.generateGroups(config)
        for branch in self.repoBranches:
            self.generateOneBranch(config, branch)
        with open(path, 'w') as fp:
            config.write(fp)

    def generateGroups(self, config):
        if not config.has_section("groups"):
            config.add_section("groups")
        for group in self.groups:
            config.set("groups", group, self.groups[group])

    def generateOneBranch(self, config, branch):
        for path in self.permissions:
            sectionName = "%s:%s" % (self.repoName, dirname(urljoin(branch, '.' + path.toPathStr() + '/')))
            print(sectionName, self.repoName, branch, path.toPathStr())
            if not config.has_section(sectionName):
                config.add_section(sectionName)
            permissionsNode = self.permissions[path]
            for group in permissionsNode:
                groupName = group
                if group != '*': 
                    groupName = "@%s" % (group)
                config.set(sectionName, groupName, permissionsNode[group])

class DirectoryNode:
    def __init__(self, name):
        self.name = name
        self.parent = None
        self.childs = {}
    
    def hasChild(self, name):
        return name in self.childs
    
    def getChild(self, name):
        return self.childs.get(name)
        
    def addChild(self, child):
        self.childs[child.name] = child
        child.setParent(self)
    
    def getChilds(self):
        return self.childs
    
    def setParent(self, parent):
        self.parent = parent

    def getParent(self):
        return self.parent
    
    def toPathStr(self):
        t = []
        node = self
        while node is not None:
            t.insert(0, node.name)
            node = node.parent
        if len(t) == 1:
            return '/'
        return '/'.join(t)

    def isParent(self, node):
        if node is None:
            return False
        return self.parent == node
    
    def isAncestor(self, node):
        if node is None:
            return False

        ancestor = self.parent
        while ancestor is not None:
            if ancestor == node:
                return True
            ancestor = ancestor.parent

        return False
        
    def __str__(self):
        return "'%s'" % self.toPathStr()
    
    def __repr__(self):
        return "<DirectoryNode '%s'>" % self.toPathStr()
    
    def __iter__(self):
        for name in self.childs:
            for item in self.childs[name]:
                yield item
        yield self
    
class DirectoryTree:
    def __init__(self, pathes):
        self.tree = DirectoryNode('')
        self.build(pathes)

    def build(self, pathes):
        for path in pathes:
            self.addDirectory(path)
        
    def addDirectory(self, path):
        names = self.decodePath(path)
        node = self.tree
        for name in names:
            child = node.getChild(name)
            if child is None:
                if name == '':
                    print("addDirectory", name, names, path)
                child = DirectoryNode(name)
                node.addChild(child)
            node = child
        return node
    
    def decodePath(self, path):
        if path == '/':
            return []
        return self.formatPath(path).split('/')

    def formatPath(self, path):
        if len(path) == 0:
            return path
        if path[len(path) - 1] == '/':
            path = dirname(path)
        if path[0] == '/':
            path = path[1:len(path)]
        return path
    
    def __str__(self):
        n = 0
        it = iter(self.tree)
        while True:
            try:
                x = next(it)
                n = n + 1
            except StopIteration:
                break
        return "Directory Tree, node=%s" % (n)

    def hasDirectory(self, path):
        names = self.decodePath(path)
        node = self.tree
        for name in names:
            child = node.getChild(name)
            if child is None:
                return False
            node = child

class SvnProxy:
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        self.dirs = []

    def getAllDirectories(self):
        # bash = 'svn list %s --username %s --password %s -R | grep "/$"' % (self.url, self.username, self.password)
        bash = 'svn list %s --username %s --password %s -R' % (self.url, self.username, self.password)
        completed = subprocess.run(bash, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            return []
        subs = completed.stdout.decode('utf-8').splitlines()
        return subs

    def getSubDirectories(self, path):
        url = join(self.url, path)
        bash = 'svn list %s --username %s --password %s | grep "/$"' % (url, self.username, self.password)
        completed = subprocess.run(bash, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            print("!! no such directory", url)
            return []

        subs = completed.stdout.decode('utf-8').splitlines()
        return list(map(lambda x: join(path, x), subs))

def main():
    config = ConfigParser()
    config.read("./config.ini")

    svnUrl = config.get("svn", "url")
    svnUsername = config.get("svn", "username")
    svnPassword = config.get("svn", "password")

    svn = SvnProxy(svnUrl, svnUsername, svnPassword)
    dirs = svn.getAllDirectories()
    tree = DirectoryTree(dirs)
    generator = Generator(tree)
    generator.parse(config)
    generator.generate('./authz')


if __name__ == "__main__":
    main()
