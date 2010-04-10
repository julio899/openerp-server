# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import time
from osv import fields,osv
from tools.safe_eval import safe_eval
import pooler
import logging

class ir_sequence_type(osv.osv):
    _name = 'ir.sequence.type'
    _columns = {
        'name': fields.char('Sequence Name',size=64, required=True),
        'code': fields.char('Sequence Code',size=32, required=True),
    }
ir_sequence_type()

def _code_get(self, cr, uid, context={}):
    cr.execute('select code, name from ir_sequence_type')
    return cr.fetchall()

class ir_sequence(osv.osv):
    _name = 'ir.sequence'
    _columns = {
        'name': fields.char('Sequence Name',size=64, required=True),
        'code': fields.selection(_code_get, 'Sequence Code',size=64, required=True),
        'active': fields.boolean('Active'),
        'prefix': fields.char('Prefix',size=64),
        'suffix': fields.char('Suffix',size=64),
        'number_next': fields.integer('Next Number', required=True),
        'number_increment': fields.integer('Increment Number', required=True),
        'padding' : fields.integer('Number padding', required=True, help="OpenERP will automatically adds some '0' on the left of the 'Next Number' to get the required padding size."),
        'company_id': fields.many2one('res.company', 'Company'),
	'condition': fields.char('Condition', size=250, help="If set, sequence will only be used in case this python expression matches, and will precede other sequences."),
	'weight': fields.integer('Weight',required=True, help="If two sequences match, the highest weight will be used.")
    }
    _defaults = {
        'active': lambda *a: True,
        'company_id': lambda s,cr,uid,c: s.pool.get('res.company')._company_default_get(cr, uid, 'ir.sequence', context=c),
        'number_increment': lambda *a: 1,
        'number_next': lambda *a: 1,
        'padding' : lambda *a : 0,
	'weight' : lambda *a: 10,
    }

    def _process(self, s):
        return (s or '') % {
            'year':time.strftime('%Y'),
            'month': time.strftime('%m'),
            'day':time.strftime('%d'),
            'y': time.strftime('%y'),
            'doy': time.strftime('%j'),
            'woy': time.strftime('%W'),
            'weekday': time.strftime('%w'),
            'h24': time.strftime('%H'),
            'h12': time.strftime('%I'),
            'min': time.strftime('%M'),
            'sec': time.strftime('%S'),
        }

    def _get_test(self, test, context):
        _irs_tests = { 'code': 'code=%s', 'id': 'id=%s' }
        if test not in _irs_tests:
            raise Exception('The test "%s" is not valid for ir.sequence.get_id()' % test)
        return _irs_tests[test]
    
    def get_id(self, cr, uid, sequence_id, test='id', context=None):
        if not context:
            context = {}
        log = logging.getLogger('orm')
        try:
            sql_test = self._get_test(test, context)
            cr.execute('SELECT id, number_next, prefix, suffix, padding, condition \
                FROM ir_sequence \
                WHERE '+sql_test+' AND active=%s ORDER BY weight DESC, length(COALESCE(condition,\'\')) DESC \
                FOR UPDATE', (sequence_id, True), debug=self._debug)
            for res in cr.dictfetchall():
                if res['condition']:
                    if self._debug:
                        log.debug("ir_seq: %s has condition: %s" %(res['id'], res['condition']))
                    try:
                        bo = safe_eval(res['condition'],context)
                        if not bo:
                            if self._debug:
                                log.debug('ir_seq: %d not matched' % res['id'])
                            continue
                    except Exception,e:
                        # it would be normal to have exceptions, because
                        # the domain may contain errors
                        if self._debug:
                            log.exception('ir_seq[%d]: Exception %s with context %s' % \
                                                (res['id'], context, e))
                        continue
                    if self._debug:
                        log.debug('ir_seq: %d matched' % res['id'])

                cr.execute('UPDATE ir_sequence '
                        'SET number_next=number_next+number_increment '
                        'WHERE id=%s AND active=%s', 
                        (res['id'], True),
                        debug=self._debug)
                if res['number_next']:
                    return self._process(res['prefix']) + '%%0%sd' % res['padding'] % res['number_next'] + self._process(res['suffix'])
                else:
                    return self._process(res['prefix']) + self._process(res['suffix'])
            
            # end for
        finally:
            cr.commit()
        return False

    def get(self, cr, uid, code, context = None):
        return self.get_id(cr, uid, code, test='code',context=context)
ir_sequence()


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
