# BEGIN_COPYRIGHT
#
# Copyright 2009-2016 CRS4.
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

from timer import Timer

import jpyutil
jvm = jpyutil.init_jvm(jvm_maxmem='48M')

import jpy

N = 256
z = '\xff' * N * 1024
with Timer() as t:
    bz = bytearray(z)  # view string as bytearray
    a = jpy.array('byte', bz)  # project this to a java array
    ba = bytearray(a)  # bring it back to a python bytearray
print "=> round trip for size %sKB: %ss [%s KB/sec]" % (N, t.secs, N / t.secs)