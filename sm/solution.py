#   Copyright 2012 David Malcolm <dmalcolm@redhat.com>
#   Copyright 2012 Red Hat, Inc.
#
#   This is free software: you can redistribute it and/or modify it
#   under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful, but
#   WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#   General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see
#   <http://www.gnu.org/licenses/>.


# We could create a separate graph, but it's probably easier
# to simply add the state information directly to the node
# It's the dot visualization we want, though, that makes it easy to debug

from gccutils.graph import Graph, Node, Edge
from gccutils import invoke_dot

num_error_graphs = 0

class ErrorGraph(Graph):
    # An exploded graph, culled to only the nodes of interest
    # for a specific error
    def __init__(self, ctxt, innergraph):
        Graph.__init__(self)
        self.ctxt = ctxt
        self.innergraph = innergraph
        self.node_for_triple = {}
        self.edgedict = {}

    def add_node(self, node):
        # Lazily add nodes, discarding duplicates:
        key = (node.innernode, node.expr, node.state)
        if key in self.node_for_triple:
            # Already present:
            return self.node_for_triple[key], False
        else:
            self.node_for_triple[key] = node
            return Graph.add_node(self, node), True

    def add_edge(self, srcnode, dstnode, inneredge):
        # Lazily add nodes, discarding duplicates:
        key = (srcnode, dstnode, inneredge)
        if key in self.edgedict:
            return self.edgedict[key]
        else:
            e = Graph.add_edge(self, srcnode, dstnode, inneredge)
            self.edgedict[key] = e
            return e

    def _make_edge(self, srcnode, dstnode, inneredge):
        return ErrorEdge(srcnode, dstnode, inneredge)

    def get_entry_nodes(self):
        for srcnode in self.innergraph.get_entry_nodes():
            srctriple = (srcnode,
                         None,
                         self.ctxt.get_default_state())
            if srctriple in self.node_for_triple:
                yield self.node_for_triple[srctriple]

class ErrorNode(Node):
    def __init__(self, innernode, expr, state, match):
        Node.__init__(self)
        self.innernode = innernode
        self.expr = expr
        self.state = state
        self.match = match

    def __repr__(self):
        return 'ErrorNode(%r, %r, %r, %r)' % (self.innernode, self.expr, self.state, self.match)

    def to_dot_html(self, ctxt):
        from gccutils.dot import Table, Tr, Td, Text, Br, Font

        inner = self.innernode.to_dot_html(self)
        table = Table(cellborder=1)
        tr = table.add_child(Tr())
        td = tr.add_child(Td(align='left'))
        td.add_child(Text('expr: %s' % self.expr))
        tr = table.add_child(Tr())
        td = tr.add_child(Td(align='left'))
        td.add_child(Text('state: %s' % self.state))
        tr = table.add_child(Tr())
        td = tr.add_child(Td(align='left'))
        td.add_child(Text('match: %s' % self.match))
        if self.facts._facts:
            for fact in self.facts._facts:
                tr = table.add_child(Tr())
                td = tr.add_child(Td(align='left'))
                td.add_child(Text('FACT: %s' % (fact, )))
                #td.add_child(Text('FACT: %r' % fact))
        else:
            tr = table.add_child(Tr())
            td = tr.add_child(Td(align='left'))
            td.add_child(Text('NO FACTS'))
        tr = table.add_child(Tr())
        td = tr.add_child(Td(align='left'))
        td.add_child(inner)
        return table

    @property
    def stmt(self):
        return self.innernode.stmt

class ErrorEdge(Edge):
    def __init__(self, srcnode, dstnode, inneredge):
        Edge.__init__(self, srcnode, dstnode)
        self.inneredge = inneredge

    def to_dot_label(self, ctxt):
        return self.inneredge.to_dot_label(ctxt)

    @property
    def true_value(self):
        return self.inneredge.true_value

    @property
    def false_value(self):
        return self.inneredge.false_value

class Solution:
    def __init__(self, ctx):
        self.ctxt = ctx

        # dict from SupergraphNode to dict from expr to (oldstate, newstate)
        # pair:
        #   self.changes[node][expr] == (oldstate, newstate)
        # (where oldstate might equal newstate).
        self.changes = {}
        self.states = {}
        for node in self.ctxt.graph.nodes:
            self.changes[node] = {}
            self.states[node] = {}

    def dump(self, out):
        from gccutils import get_src_for_loc

        global _indent
        _indent = 0
        def writeln(line, indent=0):
            global _indent
            _indent += indent
            out.write(' ' * _indent)
            out.write(line)
            out.write('\n')
            _indent -= indent

        writeln('SOLUTION FOR %s' % self.ctxt.sm.name)
        _indent += 2

        writeln('; underlying graph has: %i nodes  %i edges'
                  % (len(self.ctxt.graph.nodes),
                     len(self.ctxt.graph.edges)))

        # 1st pass: enumerate nodes in topologically-sorted order:
        nodes = self.ctxt.graph.topologically_sorted_nodes()
        index_for_node = {}
        node_for_index = {}
        for i, node in enumerate(nodes):
            index_for_node[node] = i
            node_for_index[i] = node

        # 2nd pass: write out the nodes with their edges:
        for i, node in enumerate(nodes):
            # Write the node:
            writeln('%i: %s' % (i, node))
            _indent += 4
            if node.stmt:
                if node.stmt.loc:
                    writeln('src: %s: %s' % (node.stmt.loc, get_src_for_loc(node.stmt.loc)))
            writeln('facts: %s' % node.facts)
            writeln('partitions: {%s}'
                    % ', '.join(['{%s}' % ', '.join([str(expr)
                                                     for expr in equivcls])
                                 for equivcls in node.facts.get_equiv_classes()]))
            # Write out state information:
            states = self.states[node]
            if states:
                writeln('reachable states:')
                for item in states:
                    for expr in states:
                        writeln('%s: %s'
                                % (expr, ',' .join(str(state)
                                                   for state in states[expr])),
                                indent=2)
            else:
                writeln('NOT REACHED', indent=4)
            _indent -= 2

            changes = self.changes[node]
            for edge in node.succs:
                if edge.true_value:
                    boolstr = "true: "
                elif edge.false_value:
                    boolstr = "false: "
                else:
                    boolstr = ""
                writeln('%sgoto %i;' % (boolstr, index_for_node[edge.dstnode]),
                        indent=2)
                for key in changes:
                    srcexpr, srcstate = key
                    for dstitem in changes[key]:
                        if dstitem.node == edge.dstnode:
                            if dstitem.match:
                                matchstr = ' (via %s)' % dstitem.match.description(self.ctxt)
                            else:
                                matchstr = ''
                            if srcexpr == dstitem.state and srcstate == dstitem.state:
                                writeln('propagation of %s: %s'
                                        % (srcexpr, srcstate),
                                        indent=4)
                            else:
                                writeln('change from %s: %s  to  %s: %s%s'
                                        % (srcexpr, srcstate,
                                           dstitem.expr, dstitem.state,
                                           matchstr),
                                        indent=4)
            _indent -= 2

    def to_dot(self, name):
        # (a handy debug method is essential)
        # basically we want to reuse the underlying graph's to_dot, but
        # use some diferent policy...
        class SolutionRenderer:
            def __init__(self, solution):
                self.solution = solution
            def node_to_dot_html(self, node):
                # raise foo # FIXME: we'll annotate this:
                from gccutils.dot import Table, Tr, Td, Text, Br, Font

                inner = node.to_dot_html(self)
                table = Table(cellborder=1)
                states = self.solution.states[node]
                if states:
                    for expr in states:
                        tr = table.add_child(Tr())
                        td = tr.add_child(Td(align='left'))
                        td.add_child(Text('%s: %s'
                                          % (expr, ',' .join(str(state)
                                                            for state in states[expr]))))
                else:
                    tr = table.add_child(Tr())
                    td = tr.add_child(Td(align='left'))
                    td.add_child(Text('NOT REACHED'))

                """
                changes = self.solution.changes[node]
                if changes:
                    for key in changes:
                        for item in changes[key]:
                            tr = table.add_child(Tr())
                            td = tr.add_child(Td(align='left'))
                            td.add_child(Text('CHANGE FROM %s TO %s'
                                          % (key, item)))
                else:
                    tr = table.add_child(Tr())
                    td = tr.add_child(Td(align='left'))
                    td.add_child(Text('NO CHANGES'))
                """
                if node.facts._facts:
                    for fact in node.facts._facts:
                        tr = table.add_child(Tr())
                        td = tr.add_child(Td(align='left'))
                        td.add_child(Text('FACT: %s' % (fact, )))
                        #td.add_child(Text('FACT: %r' % fact))
                else:
                    tr = table.add_child(Tr())
                    td = tr.add_child(Td(align='left'))
                    td.add_child(Text('NO FACTS'))
                tr = table.add_child(Tr())
                td = tr.add_child(Td(align='left'))
                td.add_child(inner)
                return table

        return self.ctxt.graph.to_dot(name, SolutionRenderer(self))


    def build_error_graph(self, dstnode, expr, state):
        errgraph = ErrorGraph(self.ctxt, self.ctxt.graph)
        dsterrnode, _ = errgraph.add_node(ErrorNode(dstnode, expr, state, None))

        # srcnodes = list(innergraph.get_entry_nodes())
        worklist = [dsterrnode]
        while worklist:
            errnode = worklist[0]
            worklist = worklist[1:]

            self.ctxt.debug('considering routes to errnode: %s', errnode)

            dstsupernode = errnode.innernode

            # backtrack to find nodes that lead to errnode,
            # lazily adding them:
            for edge in dstsupernode.preds:
                srcsupernode = edge.srcnode
                self.ctxt.debug('considering srcnode: %s', srcsupernode)
                changesdict = self.changes[srcsupernode]
                for key in changesdict:
                    self.ctxt.debug('key: %s', key)
                    srcexpr, srcstate = key
                    for item in changesdict[key]:
                        self.ctxt.debug('item: %s', item)
                        if item.node == errnode.innernode:
                            # The items must match, unless the srcnode is
                            # None, in which case it's legitimate to
                            # transition to a more specific expr:
                            if item.expr == errnode.expr or item.expr is None:
                                if item.state == errnode.state:
                                    srcerrnode, new = errgraph.add_node(ErrorNode(srcsupernode,
                                                                                  srcexpr,
                                                                                  srcstate,
                                                                                  item.match))
                                    errgraph.add_edge(srcerrnode, errnode, edge)
                                    if new:
                                        worklist.append(srcerrnode)
                                        self.ctxt.debug('added')
                                    else:
                                        self.ctxt.debug('already present')
        return errgraph

    def get_shortest_path_to(self, dstnode, expr, state):
        # backtrack from destination until you reach a srcnode whilst
        # obeying various restrictions:
        #   * exprs/states have to match (or have state transitions)
        #   * call stack has to be obeyed: return to correct caller
        #   * perhaps some simple rules about known "state", to suppress
        #   the most obvious false positives

        self.ctxt.debug('get_shortest_path_to:')
        self.ctxt.debug('  dstnode: %s', dstnode)
        self.ctxt.debug('  expr: %s', expr)
        self.ctxt.debug('  state: %s', state)

        self.ctxt.log('building error graph')
        with self.ctxt.indent():
            errgraph = self.build_error_graph(dstnode, expr, state)

            from sm.facts import find_facts, remove_impossible

            find_facts(self.ctxt, errgraph)
            changes = remove_impossible(self.ctxt, errgraph)
            # Removing impossible nodes may lead to more facts being known;
            # keep going until you can't remove any more:
            while changes:
                find_facts(self.ctxt, errgraph)
                changes = remove_impossible(self.ctxt, errgraph)

            dsttriple = (dstnode,
                         expr,
                         state)
            dsterrnode = errgraph.node_for_triple[dsttriple]
            if dsterrnode not in errgraph.nodes:
                self.ctxt.log('dsttriple removed from errgraph')
                return None

            from sm.solver import SHOW_ERROR_GRAPH
            if SHOW_ERROR_GRAPH:
                global num_error_graphs
                num_error_graphs += 1
                name = 'error_graph_%i' % num_error_graphs
                dot = errgraph.to_dot(name)
                invoke_dot(dot, name)
        self.ctxt.log('calculating shortest path through error graph')
        with self.ctxt.indent():
            shortestpath = None
            for srcnode in self.ctxt.graph.get_entry_nodes():
                self.ctxt.log('considering paths from %s' % srcnode)
                with self.ctxt.indent():
                    srctriple = (srcnode,
                                 None,
                                 self.ctxt.get_default_state())
                    if srctriple in errgraph.node_for_triple:
                        srcerrnode = errgraph.node_for_triple[srctriple]
                        path = errgraph.get_shortest_path(srcerrnode, dsterrnode)
                        if shortestpath is not None:
                            if len(path) < len(shortestpath):
                                shortestpath = path
                        else:
                            shortestpath = path
                    else:
                        self.ctxt.log('srctriple not present in errgraph')
        return shortestpath
