# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP-f3, Open Source Management Solution
#    Copyright (C) 2008-2011 P. Christeas <xrg@hellug.gr>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

#.apidoc title: Framework fields

""" Framework fields are implicit fields that are used by the ORM framework
    to convey special data. User can `not` directly manipulate the contents
    of these fields.
"""
from fields import _column, register_field_classes
from fields import integer
#import tools
from tools.translate import _
from tools import expr_utils as eu

class id_field(integer):
    """ special properties for the 'id' field
    """
    merge_op = True

    def expr_eval(self, cr, uid, obj, lefts, operator, right, pexpr, context):
        """ The magic 'id' field has utility expression syntax

            Of course, this syntax is supported::

                [ '|', ('id', '=', 4), ('id', 'in', (1,2,3))]

            but also, ir.model.data queries can be triggered like::

                [('id.ref', '=', 'module.xml_id') ]

            or even, for external refs::

                [('id.ref.magento', '=', 'foo.bar')]
                or
                [('id.ref.magento.foo', '=', 'bar')]
        """
        if len(lefts) > 1:
            import expression
            from query import Query
            if lefts[1] == 'ref':
                lop = None
                sop = 'in'
                source = ['orm', 'xml']
                module = False
                domain = [('model', '=', obj._name)]

                if operator == '=':
                    lop = 'inselect'
                elif operator in ('!=', '<>'):
                    lop = 'not inselect'
                # elif 'in' => 'inselect', in
                else:
                    raise eu.DomainInvalidOperator(obj, lefts, operator, right)

                if len(lefts) > 2:
                    sop = '='
                    source = lefts[2]
                if len(lefts) > 3:
                    module = lefts[3]
                if len(lefts) > 4:
                    raise eu.DomainLeftError(obj, lefts, operator, right)

                if operator in ('=', '!=', '<>'):
                    if not isinstance(right, basestring):
                        raise eu.DomainRightError(obj, lefts, operator, right)
                    if '.' in right:
                        module, name = right.split('.', 1)
                    elif module:
                        name = right
                    elif context and 'module' in context:
                        module = context
                        name = right
                    else:
                        raise eu.DomainMsgError(_("Ref Id does not define module, cannot decode: %s") % right)

                    domain += [('module', '=', module), ('name', '=', name),
                                ('source', sop, source)]

                imd_obj = obj.pool.get('ir.model.data')
                qry = Query(tables=['"%s"' % imd_obj._table,])
                e = expression.expression(domain, debug=imd_obj._debug)
                e.parse_into_query(cr, uid, imd_obj, qry, context)

                from_clause, where_clause, qry_args = qry.get_sql()
                qry = "SELECT res_id FROM %s WHERE %s" % (from_clause, where_clause)

                return (lefts[0], lop, (qry, qry_args))
            else:
                raise eu.DomainLeftError(obj, lefts, operator, right)

        if operator == 'child_of' or operator == '|child_of':
            dom = pexpr._rec_get(cr, uid, obj, right, null_too=(operator == '|child_of'), context=context)
            if len(dom) == 0:
                return True
            elif len(dom) == 1:
                return dom[0]
            else:
                return eu.nested_expr(dom)
        else:
            # Copy-paste logic from super, save on the function call
            assert len(lefts) == 1, lefts
            if right is False:
                if operator not in ('=', '!=', '<>'):
                    raise eu.DomainInvalidOperator(obj, lefts, operator, right)
                return (lefts[0], operator, None)
            return None # as-is


class vptr_field(_column):
    """Pseydo-field for the implicit _vptr column
    
        This will expose some helper functions that allow smart operations on
        the _vptr.
    """
    pass

    def _auto_init_sql(self, name, obj, schema_table, context=None):
        return None

class vptr_name(_column):
    """ Exposes the human readable name of the associated class

        This is a pseydo-function field with implied functionality.
        It will search `ir.model` and yield the corresponding model names,
        for the records of "our" model requested.
    """
    _classic_read = False
    _classic_write = False
    _prefetch = False
    _type = 'char'
    _properties = True
    merge_op = True

    def __init__(self, string='Class'):
        _column.__init__(self, string=string, size=128, readonly=True)

    def get(self, cr, obj, ids, name, user=None, context=None, values=None):
        from orm import browse_record_list, only_ids
        if not obj._vtable:
            return dict.fromkeys(only_ids(ids), False)

        res_ids = {}
        vptrs_resolve = {}
        if isinstance(ids, browse_record_list):
            for bro in ids:
                res_ids[bro.id] = bro._vptr
                vptrs_resolve[bro._vptr] = False
        else:
            # clasic read:
            for ores in obj.read(cr, user, ids, fields=['_vptr'], context=context):
                res_ids[ores['id']] = ores['_vptr']
                vptrs_resolve[ores['_vptr']] = False

        for mres in obj.pool.get('ir.model').search_read(cr, user, \
                [('model', 'in', vptrs_resolve.keys())], \
                fields=['model', 'name'], context=context):
            # context is important, we want mres to be translated
            vptrs_resolve[mres['model']] = mres['name']

        res = {}
        for rid, rmod in res_ids.items():
            res[rid] = vptrs_resolve.get(rmod, False)

        return res

        #if name == '_vptr.name':
        #    # retrieve the model name, translated
        #    pass

    def _auto_init_sql(self, name, obj, schema_table, context=None):
        return None

register_field_classes(id_field, vptr_field, vptr_name)

#eof