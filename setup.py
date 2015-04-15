# BEGIN_COPYRIGHT
#
# Copyright 2009-2015 CRS4.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# END_COPYRIGHT

"""
Important environment variables
-------------------------------

The Pydoop setup looks in a number of default paths for what it
needs.  If necessary, you can override its behaviour or provide an
alternative path by exporting the environment variables below::

  JAVA_HOME, e.g., /opt/sun-jdk
  HADOOP_HOME, e.g., /opt/hadoop-1.0.2

Other relevant environment variables include::

  HADOOP_VERSION, e.g., 0.20.2-cdh3u4 (override Hadoop's version string).
"""

import time
import os
import glob
import shutil
import subprocess

SETUPTOOLS_MIN_VER = '3.3'

import setuptools
from pkg_resources import parse_version  # included in setuptools
print 'using setuptools version', setuptools.__version__
if parse_version(setuptools.__version__) < parse_version(SETUPTOOLS_MIN_VER):
    raise RuntimeError(
        'setuptools minimum required version: %s' % SETUPTOOLS_MIN_VER
    )

# bug: http://bugs.python.org/issue1222585
# workaround: http://stackoverflow.com/questions/8106258
from distutils.sysconfig import get_config_var
_UNWANTED_OPTS = frozenset(['-Wstrict-prototypes'])
os.environ['OPT'] = ' '.join(
    _ for _ in get_config_var('OPT').strip().split() if _ not in _UNWANTED_OPTS
)

from setuptools import setup, find_packages, Extension
from distutils.command.build import build
from distutils.command.clean import clean
from distutils.errors import DistutilsSetupError, DistutilsOptionError
from distutils import log

import pydoop
import pydoop.utils.jvm as jvm
import pydoop.hdfs.core.impl as hdfsimpl

JAVA_HOME = jvm.get_java_home()
JVM_LIB_PATH, JVM_LIB_NAME = jvm.get_jvm_lib_path_and_name(JAVA_HOME)

HADOOP_HOME = pydoop.hadoop_home(fallback=None)
HADOOP_VERSION_INFO = pydoop.hadoop_version_info()

EXTENSION_MODULES = []
GIT_COMMIT_FN = ".git_commit"
EXTRA_COMPILE_ARGS = ["-Wno-write-strings"]  # http://bugs.python.org/issue6952

# properties file.  Since the source is in the root dir, filename = basename
PROP_FN = PROP_BN = pydoop.__propfile_basename__


# ---------
# UTILITIES
# ---------

def rm_rf(path, dry_run=False):
    """
    Remove a file or directory tree.

    Won't throw an exception, even if the removal fails.
    """
    log.info("removing %s" % path)
    if dry_run:
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError:
        pass


def mtime(fn):
    return os.stat(fn).st_mtime


def must_generate(target, prerequisites):
    try:
        return max(mtime(p) for p in prerequisites) > mtime(target)
    except OSError:
        return True


def get_version_string(filename="VERSION"):
    try:
        with open(filename) as f:
            return f.read().strip()
    except IOError:
        raise DistutilsSetupError("failed to read version info")


def write_config(filename="pydoop/config.py", hdfs_core_impl=hdfsimpl.DEFAULT):
    prereq = "DEFAULT_HADOOP_HOME"
    if not os.path.exists(prereq):
        with open(prereq, "w") as f:
            f.write("%s\n" % HADOOP_HOME)
    # if must_generate(filename, [prereq]):
    with open(filename, "w") as f:
        f.write("# GENERATED BY setup.py\n")
        f.write("DEFAULT_HADOOP_HOME='%s'\n" % HADOOP_HOME)
        f.write("HDFS_CORE_IMPL='%s'\n" % hdfs_core_impl)


def generate_hdfs_config():
    """
    Generate config.h for libhdfs.

    This is only relevant for recent Hadoop versions.
    """
    config_fn = os.path.join(
        'src', 'libhdfsV2', "config.h"
    )
    with open(config_fn, "w") as f:
        f.write("#ifndef CONFIG_H\n#define CONFIG_H\n")
        if have_better_tls():
            f.write("#define HAVE_BETTER_TLS\n")
        f.write("#endif\n")


def get_git_commit():
    if os.path.isfile(GIT_COMMIT_FN):
        with open(GIT_COMMIT_FN) as f:
            return f.read().strip()
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD']
        ).rstrip('\n')
    except subprocess.CalledProcessError:
        return None


def write_version(filename="pydoop/version.py"):
    prereq = "VERSION"
    if must_generate(filename, [prereq]):
        version = get_version_string(filename=prereq)
        git_commit = get_git_commit()
        with open(filename, "w") as f:
            f.write("# GENERATED BY setup.py\n")
            f.write("version='%s%s'\n" % (
                version, '' if git_commit is None else (' [%s]' % git_commit))
            )


def build_hdfscore_native_impl():
    generate_hdfs_config()
    hdfs_ext_sources = []
    hadoop_t = HADOOP_VERSION_INFO.tuple
    if hadoop_t >= (2, 0, 0):
        hdfs_ext_sources += glob.glob('src/libhdfsV2/*.c')
        hdfs_ext_sources += glob.glob('src/libhdfsV2/common/*.c')
        hdfs_ext_sources += glob.glob('src/libhdfsV2/os/posix/*.c')
        libhdfs_macros = [("HADOOP_LIBHDFS_V2", 1)]
        inc_dirs = (jvm.get_include_dirs() +
                    ['src/libhdfsV2', 'src/libhdfsV2/os/posix'])
    else:
        src_dir = 'src/libhdfs/%d.%d.%d' % hadoop_t[0:3]
        hdfs_ext_sources += glob.glob(os.path.join(src_dir, '*.c'))
        inc_dirs = jvm.get_include_dirs() + [src_dir]
        libhdfs_macros = [("HADOOP_LIBHDFS_V1", 1)]
    hdfs_ext_sources += glob.glob('src/native_core_hdfs/*.cc')
    native_hdfs_core = Extension(
        'pydoop.native_core_hdfs',
        include_dirs=inc_dirs,
        libraries=jvm.get_libraries(),
        library_dirs=[JAVA_HOME + "/Libraries", JVM_LIB_PATH],
        sources=hdfs_ext_sources,
        define_macros=jvm.get_macros() + libhdfs_macros,
        extra_compile_args=EXTRA_COMPILE_ARGS,
        extra_link_args=['-Wl,-rpath,%s' % JVM_LIB_PATH]
    )
    EXTENSION_MODULES.append(native_hdfs_core)


def build_sercore_extension():
    extra_compile_args = EXTRA_COMPILE_ARGS + ["-O3"]
    binary_encoder = Extension(
        'pydoop.sercore',
        sources=[os.path.join('src/serialize', x) for x in [
            'protocol_codec.cc', 'SerialUtils.cc', 'StringUtils.cc'
        ]],
        extra_compile_args=extra_compile_args
    )
    EXTENSION_MODULES.append(binary_encoder)


def have_better_tls():
    """
    See ${HADOOP_HOME}/hadoop-hdfs-project/hadoop-hdfs/src/CMakeLists.txt
    """
    return False  # FIXME: need a portable implementation


# ------------
# BUILD ENGINE
# ------------

class JavaLib(object):

    def __init__(self, hadoop_vinfo):
        self.hadoop_vinfo = hadoop_vinfo
        self.jar_name = pydoop.jar_name(self.hadoop_vinfo)
        self.classpath = pydoop.hadoop_classpath()
        self.java_files = []
        self.dependencies = []
        self.properties = []
        if (hadoop_vinfo.main >= (2, 0, 0)
            and (not hadoop_vinfo.is_cloudera()
                 or hadoop_vinfo.is_yarn())):
            # FIXME: kinda hardwired to avro for now
            self.properties.append((os.path.join(
                "it/crs4/pydoop/mapreduce/pipes", PROP_BN),
                PROP_FN))
            # -- pydoop script is currently using v1
            self.java_files.extend([
                "src/v1/it/crs4/pydoop/NoSeparatorTextOutputFormat.java"
            ])
            self.java_files.extend(glob.glob(
                'src/v2/it/crs4/pydoop/pipes/*.java'
            ))
            self.java_files.extend(glob.glob(
                'src/v2/it/crs4/pydoop/mapreduce/pipes/*.java'
            ))
            self.java_files.extend(glob.glob(
                'src/v2/it/crs4/pydoop/mapreduce/lib/output/*.java'
            ))
            # for now we have only hadoop2 deps (avro-mapred)
            self.dependencies.extend(glob.glob('lib/*.jar'))
        else:
            self.java_files.extend([
                "src/v1/it/crs4/pydoop/NoSeparatorTextOutputFormat.java"
            ])
            self.java_files.extend(glob.glob(
                'src/v1/org/apache/hadoop/mapred/pipes/*.java'
            ))


class JavaBuilder(object):

    def __init__(self, build_temp, build_lib):
        self.build_temp = build_temp
        self.build_lib = build_lib
        self.java_libs = [JavaLib(HADOOP_VERSION_INFO)]

    def run(self):
        log.info("hadoop_home: %r" % (HADOOP_HOME,))
        log.info("hadoop_version: '%s'" % HADOOP_VERSION_INFO)
        log.info("java_home: %r" % (JAVA_HOME,))
        for jlib in self.java_libs:
            self.__build_java_lib(jlib)

    def __build_java_lib(self, jlib):
        log.info("Building java code for hadoop-%s" % jlib.hadoop_vinfo)
        package_path = os.path.join(self.build_lib, "pydoop")
        compile_cmd = "javac"
        if jlib.classpath:
            classpath = [jlib.classpath]
            for src in jlib.dependencies:
                dest = os.path.join(package_path, os.path.basename(src))
                shutil.copyfile(src, dest)
                classpath.append(dest)
            compile_cmd += " -classpath %s" % (':'.join(classpath))
        else:
            log.warn(
                "WARNING: could not set classpath, java code may not compile"
            )
        class_dir = os.path.join(
            self.build_temp, "pipes"
        )
        jar_path = os.path.join(package_path, jlib.jar_name)
        if not os.path.exists(class_dir):
            os.mkdir(class_dir)
        compile_cmd += " -d '%s'" % class_dir
        log.info("Compiling Java classes")
        for f in jlib.java_files:
            compile_cmd += " %s" % f
        ret = os.system(compile_cmd)
        if ret:
            raise DistutilsSetupError(
                "Error compiling java component.  Command: %s" % compile_cmd
            )
        log.info("Copying properties file")
        for p in jlib.properties:
            prop_file_dest = os.path.join(class_dir, p[0])
            shutil.copyfile(p[1], prop_file_dest)
        log.info("Making Jar: %s", jar_path)
        package_cmd = "jar -cf %(jar_path)s -C %(class_dir)s ./it" % {
            'jar_path': jar_path, 'class_dir': class_dir
        }
        log.info("Packaging Java classes")
        log.info("Command: %s", package_cmd)
        ret = os.system(package_cmd)
        if ret:
            raise DistutilsSetupError(
                "Error packaging java component.  Command: %s" % package_cmd
            )


class BuildPydoop(build):

    user_options = build.user_options
    user_options.append((
        'hdfs-core-impl=', None,
        "hdfs core implementation [%s]" % ", ".join(hdfsimpl.SUPPORTED)
    ))

    def __init__(self, dist):
        build.__init__(self, dist)
        self.hdfs_core_impl = hdfsimpl.DEFAULT

    def finalize_options(self):
        build.finalize_options(self)
        if self.hdfs_core_impl not in hdfsimpl.SUPPORTED:
            raise DistutilsOptionError(
                '%r not supported' % (self.hdfs_core_impl,)
            )

    def build_java(self):
        jb = JavaBuilder(self.build_temp, self.build_lib)
        jb.run()

    def create_tmp(self):
        if not os.path.exists(self.build_temp):
            os.mkdir(self.build_temp)
        if not os.path.exists(self.build_lib):
            os.mkdir(self.build_lib)

    def clean_up(self):
        shutil.rmtree(self.build_temp)

    def run(self):
        print "hdfs core implementation: {0}".format(self.hdfs_core_impl)
        write_config(hdfs_core_impl=self.hdfs_core_impl)
        write_version()
        shutil.copyfile(PROP_FN, os.path.join("pydoop", PROP_BN))
        build_sercore_extension()
        if self.hdfs_core_impl == hdfsimpl.NATIVE:
            build_hdfscore_native_impl()
        build.run(self)
        try:
            self.create_tmp()
            self.build_java()
        finally:
            # On NFS, if we clean up right away we have issues with
            # NFS handles being still in the directory trees to be
            # deleted.  So, we sleep a bit and then delete
            time.sleep(0.5)
            self.clean_up()
        log.info("Build finished")


class Clean(clean):

    def run(self):
        clean.run(self)
        garbage_list = [
            "DEFAULT_HADOOP_HOME",
            "build",
            "dist",
            "pydoop.egg-info",
            "pydoop/config.py",
            "pydoop/version.py",
        ]
        for p in garbage_list:
            rm_rf(p, self.dry_run)


setup(
    name="pydoop",
    version=get_version_string(),
    description=pydoop.__doc__.strip().splitlines()[0],
    long_description=pydoop.__doc__.lstrip(),
    author=pydoop.__author__,
    author_email=pydoop.__author_email__,
    url=pydoop.__url__,
    download_url="https://pypi.python.org/pypi/pydoop",
    install_requires=['setuptools>=%s' % SETUPTOOLS_MIN_VER],
    extras_require={
        ':python_version=="2.6"': ['argparse', 'importlib'],
        'avro': ["avro>=1.7.4"],
        },
    packages=find_packages(),
    package_data={"pydoop": [PROP_FN]},
    cmdclass={
        "build": BuildPydoop,
        "clean": Clean
    },
    entry_points={'console_scripts': ['pydoop = pydoop.app.main:main']},
    platforms=["Linux"],
    ext_modules=EXTENSION_MODULES,
    license="Apache-2.0",
    keywords=["hadoop", "mapreduce"],
    classifiers=[
        "Programming Language :: Python",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Intended Audience :: Developers",
    ],
    data_files=[
        ('config', ['README.md']),
    ],
)
