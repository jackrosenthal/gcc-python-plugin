/*
   Copyright 2012 David Malcolm <dmalcolm@redhat.com>
   Copyright 2012 Red Hat, Inc.

   This is free software: you can redistribute it and/or modify it
   under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful, but
   WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
   General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see
   <http://www.gnu.org/licenses/>.
*/

#include <stdlib.h>

void test(int c)
{
  int i;
  char *buffer = (char*)malloc(256);

  for (i=0; i<255; i++) {
    buffer[i] = c; /* BUG: the malloc could have failed
                    TODO: the checker doesn't yet pick up on this due to
                    the pointer arithmetic not picking up on the state */
                   /* BUG use-after-free the second time through the loop */

    free(buffer); /* BUG: doublefree here on second time through the  loop */
  }

}
