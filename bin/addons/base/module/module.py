# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#    Copyright (C) 2010 OpenERP s.a. (<http://openerp.com>).
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
import imp
import logging
import os
import re
import urllib
import zipimport

import addons
import pooler
import release
import tools

from tools.parse_version import parse_version
from tools.translate import _

from osv import fields, osv, orm

class module_category(osv.osv):
    _name = "ir.module.category"
    _description = "Module Category"

    def _module_nbr(self,cr,uid, ids, prop, unknow_none,context):
        cr.execute('SELECT category_id, COUNT(*) FROM ir_module_module '
                'WHERE category_id = ANY (%s) OR category_id IN '
                '(SELECT id FROM ir_module_category WHERE parent_id = ANY(%s) '
                ' GROUP BY category_id', (ids, ids), debug=self._debug )
        result = dict(cr.fetchall())
        for id in ids:
            cr.execute('SELECT id FROM ir_module_category WHERE parent_id=%s', (id,), debug=self._debug)
            childs = [c for c, in cr.fetchall()]
            result[id] = reduce(lambda x,y:x+y, [result.get(c, 0) for c in childs], result.get(id, 0))
        return result

    _columns = {
        'name': fields.char("Name", size=128, required=True),
        'parent_id': fields.many2one('ir.module.category', 'Parent Category', select=True),
        'child_ids': fields.one2many('ir.module.category', 'parent_id', 'Child Categories'),
        'module_nr': fields.function(_module_nbr, method=True, string='Number of Modules', type='integer')
    }
    _order = 'name'
module_category()

class module(osv.osv):
    _name = "ir.module.module"
    _description = "Module"
    __logger = logging.getLogger('base.' + _name)

    def get_module_info(self, name):
        info = {}
        try:
            info = addons.load_information_from_description_file(name)
            if 'version' in info:
                info['version'] = release.major_version + '.' + info['version']
        except Exception:
            self.__logger.debug('Error when trying to fetch informations for '
                                'module %s', name, exc_info=True)
        return info

    def _get_latest_version(self, cr, uid, ids, field_name=None, arg=None, context={}):
        res = dict.fromkeys(ids, '')
        for m in self.browse(cr, uid, ids):
            res[m.id] = self.get_module_info(m.name).get('version', '')
        return res

    def _get_views(self, cr, uid, ids, field_name=None, arg=None, context={}):
        res = {}
        model_data_obj = self.pool.get('ir.model.data')
        view_obj = self.pool.get('ir.ui.view')
        report_obj = self.pool.get('ir.actions.report.xml')
        menu_obj = self.pool.get('ir.ui.menu')
        mlist = self.browse(cr, uid, ids, context=context)
        mnames = {}
        for m in mlist:
            mnames[m.name] = m.id
            res[m.id] = {
                'menus_by_module':'',
                'reports_by_module':'',
                'views_by_module': ''
            }
        view_id = model_data_obj.search(cr,uid,[('module','in', mnames.keys()),
            ('model','in',('ir.ui.view','ir.actions.report.xml','ir.ui.menu'))])
        for data_id in model_data_obj.browse(cr,uid,view_id,context):
            # We use try except, because views or menus may not exist
            try:
                key = data_id['model']
                if key=='ir.ui.view':
                    try:
                        v = view_obj.browse(cr,uid,data_id.res_id)
                        aa = v.inherit_id and '* INHERIT ' or ''
                        res[mnames[data_id.module]]['views_by_module'] += aa + v.name + ' ('+v.type+')\n'
                    except Exception:
                        self.__logger.debug(
                            'Unknown error while browsing ir.ui.view[%s]',
                            data_id.res_id, exc_info=True)
                elif key=='ir.actions.report.xml':
                    res[mnames[data_id.module]]['reports_by_module'] += report_obj.browse(cr,uid,data_id.res_id).name + '\n'
                elif key=='ir.ui.menu':
                    try:
                        m = menu_obj.browse(cr,uid,data_id.res_id)
                        res[mnames[data_id.module]]['menus_by_module'] += m.complete_name + '\n'
                    except Exception:
                        self.__logger.debug(
                            'Unknown error while browsing ir.ui.menu[%s]',
                            data_id.res_id, exc_info=True)
            except KeyError:
                pass
        return res

    _columns = {
        'name': fields.char("Name", size=128, readonly=True, required=True, select=True),
        'category_id': fields.many2one('ir.module.category', 'Category', readonly=True, select=True),
        'shortdesc': fields.char('Short Description', size=256, readonly=True, translate=True),
        'description': fields.text("Description", readonly=True, translate=True),
        'author': fields.char("Author", size=128, readonly=True),
        'maintainer': fields.char('Maintainer', size=128, readonly=True),
        'contributors': fields.text('Contributors', readonly=True),
        'website': fields.char("Website", size=256, readonly=True),

        # attention: Incorrect field names !!
        #   installed_version refer the latest version (the one on disk)
        #   latest_version refer the installed version (the one in database)
        #   published_version refer the version available on the repository
        'installed_version': fields.function(_get_latest_version, method=True,
            string='Latest version', type='char'),
        'latest_version': fields.char('Installed version', size=64, readonly=True),
        'published_version': fields.char('Published Version', size=64, readonly=True),

        'url': fields.char('URL', size=128, readonly=True),
        'dependencies_id': fields.one2many('ir.module.module.dependency',
            'module_id', 'Dependencies', readonly=True),
        'state': fields.selection([
            ('uninstallable','Not Installable'),
            ('uninstalled','Not Installed'),
            ('installed','Installed'),
            ('to upgrade','To be upgraded'),
            ('to remove','To be removed'),
            ('to install','To be installed')
        ], string='State', readonly=True, select=True),
        'demo': fields.boolean('Demo data'),
        'license': fields.selection([
                ('GPL-2', 'GPL Version 2'),
                ('GPL-2 or any later version', 'GPL-2 or later version'),
                ('GPL-3', 'GPL Version 3'),
                ('GPL-3 or any later version', 'GPL-3 or later version'),
                ('AGPL-3', 'Affero GPL-3'),
                ('Other OSI approved licence', 'Other OSI Approved Licence'),
                ('Other proprietary', 'Other Proprietary')
            ], string='License', readonly=True),
        'menus_by_module': fields.function(_get_views, method=True, string='Menus', type='text', multi="meta", store=True),
        'reports_by_module': fields.function(_get_views, method=True, string='Reports', type='text', multi="meta", store=True),
        'views_by_module': fields.function(_get_views, method=True, string='Views', type='text', multi="meta", store=True),
        'certificate' : fields.char('Quality Certificate', size=64, readonly=True),
        'web': fields.boolean('Has a web component', readonly=True),
    }

    _defaults = {
        'state': lambda *a: 'uninstalled',
        'demo': lambda *a: False,
        'license': lambda *a: 'AGPL-3',
        'web': False,
    }
    _order = 'name'

    _sql_constraints = [
        ('name_uniq', 'UNIQUE (name)', 'The name of the module must be unique !'),
        ('certificate_uniq', 'UNIQUE (certificate)', 'The certificate ID of the module must be unique !')
    ]

    def unlink(self, cr, uid, ids, context=None):
        if not ids:
            return True
        if isinstance(ids, (int, long)):
            ids = [ids]
        mod_names = []
        for mod in self.read(cr, uid, ids, ['state','name'], context):
            if mod['state'] in ('installed', 'to upgrade', 'to remove', 'to install'):
                raise orm.except_orm(_('Error'),
                        _('You try to remove a module that is installed or will be installed'))
            mod_names.append(mod['name'])
        #Removing the entry from ir_model_data
        ids_meta = self.pool.get('ir.model.data').search(cr, uid, [('name', '=', 'module_meta_information'), ('module', 'in', mod_names)])

        if ids_meta:
            self.pool.get('ir.model.data').unlink(cr, uid, ids_meta, context)

        return super(module, self).unlink(cr, uid, ids, context=context)

    @staticmethod
    def _check_external_dependencies(terp):
        depends = terp.get('external_dependencies')
        if not depends:
            return
        for pydep in depends.get('python', []):
            parts = pydep.split('.')
            parts.reverse()
            path = None
            while parts:
                part = parts.pop()
                try:
                    f, path, descr = imp.find_module(part, path and [path] or None)
                except ImportError:
                    raise ImportError('No module named %s' % (pydep,))

        for binary in depends.get('bin', []):
            if tools.find_in_path(binary) is None:
                raise Exception('Unable to find %r in path' % (binary,))


    def state_update(self, cr, uid, ids, newstate, states_to_update, context={}, level=100):
        if level<1:
            raise orm.except_orm(_('Error'), _('Recursion error in modules dependencies !'))
        demo = False
        for module in self.browse(cr, uid, ids):
            mdemo = False
            for dep in module.dependencies_id:
                if dep.state == 'unknown':
                    raise orm.except_orm(_('Error'), _("You try to install the module '%s' that depends on the module:'%s'.\nBut this module is not available in your system.") % (module.name, dep.name,))
                ids2 = self.search(cr, uid, [('name','=',dep.name)])
                if dep.state != newstate:
                    mdemo = self.state_update(cr, uid, ids2, newstate, states_to_update, context, level-1,) or mdemo
                else:
                    od = self.browse(cr, uid, ids2)[0]
                    mdemo = od.demo or mdemo

            terp = self.get_module_info(module.name)
            try:
                self._check_external_dependencies(terp)
            except Exception, e:
                raise orm.except_orm(_('Error'), _('Unable %s the module "%s" because an external dependencie is not met: %s' % (newstate, module.name, e.args[0])))
            if not module.dependencies_id:
                mdemo = module.demo
            if module.state in states_to_update:
                self.write(cr, uid, [module.id], {'state': newstate, 'demo':mdemo})
            demo = demo or mdemo
        return demo

    def button_install(self, cr, uid, ids, context={}):
        return self.state_update(cr, uid, ids, 'to install', ['uninstalled'], context)

    def button_install_cancel(self, cr, uid, ids, context={}):
        self.write(cr, uid, ids, {'state': 'uninstalled', 'demo':False})
        return True

    def button_uninstall(self, cr, uid, ids, context={}):
        for module in self.browse(cr, uid, ids):
            cr.execute('''SELECT m.state,m.name
                FROM ir_module_module_dependency d
                JOIN ir_module_module m ON (d.module_id=m.id)
                WHERE d.name=%s 
                  AND m.state NOT IN ('uninstalled','uninstallable','to remove')''', (module.name,), debug=self._debug)
            res = cr.fetchall()
            if res:
                raise orm.except_orm(_('Error'), _('Some installed modules depend on the module you plan to Uninstall :\n %s') % '\n'.join(map(lambda x: '\t%s: %s' % (x[0], x[1]), res)))
        self.write(cr, uid, ids, {'state': 'to remove'})
        return True

    def button_uninstall_cancel(self, cr, uid, ids, context={}):
        self.write(cr, uid, ids, {'state': 'installed'})
        return True

    def button_upgrade(self, cr, uid, ids, context=None):
        depobj = self.pool.get('ir.module.module.dependency')
        todo = self.browse(cr, uid, ids, context=context)
        self.update_list(cr, uid)

        i = 0
        while i<len(todo):
            mod = todo[i]
            i += 1
            if mod.state not in ('installed','to upgrade'):
                raise orm.except_orm(_('Error'),
                        _("Can not upgrade module '%s'. It is not installed.") % (mod.name,))
            iids = depobj.search(cr, uid, [('name', '=', mod.name)], context=context)
            for dep in depobj.browse(cr, uid, iids, context=context):
                if dep.module_id.state=='installed' and dep.module_id not in todo:
                    todo.append(dep.module_id)

        ids = map(lambda x: x.id, todo)
        self.write(cr, uid, ids, {'state':'to upgrade'}, context=context)

        to_install = []
        for mod in todo:
            for dep in mod.dependencies_id:
                if dep.state == 'unknown':
                    raise orm.except_orm(_('Error'), _('You try to upgrade a module that depends on the module: %s.\nBut this module is not available in your system.') % (dep.name,))
                if dep.state == 'uninstalled':
                    ids2 = self.search(cr, uid, [('name','=',dep.name)])
                    to_install.extend(ids2)

        self.button_install(cr, uid, to_install, context=context)
        return True

    def button_upgrade_cancel(self, cr, uid, ids, context={}):
        self.write(cr, uid, ids, {'state': 'installed'})
        return True
    def button_update_translations(self, cr, uid, ids, context=None):
        self.update_translations(cr, uid, ids)
        return True

    @staticmethod
    def get_values_from_terp(terp):
        return {
            'description': terp.get('description', ''),
            'shortdesc': terp.get('name', ''),
            'author': terp.get('author', 'Unknown'),
            'maintainer': terp.get('maintainer', False),
            'contributors': ', '.join(terp.get('contributors', [])) or False,
            'website': terp.get('website', ''),
            'license': terp.get('license', 'GPL-2'),
            'certificate': terp.get('certificate') or False,
            'web': terp.get('web') or False,
        }

    # update the list of available packages
    def update_list(self, cr, uid, context=None):
        if context is None:
            context = {}
        log = logging.getLogger('init')
        res = [0, 0] # [update, add]

        all_mod_ids = self.search(cr, uid, [], context=context)
        known_module_names = addons.get_modules()
        
        def ifustr(var):
            """ Auto-convert all strings to unicode"""
            if isinstance(var, basestring):
                return tools.ustr(var)
            else:
                return var
        
        for old_mod in self.browse(cr, uid, all_mod_ids, context=context):
            if old_mod.name in known_module_names:
                known_module_names.remove(old_mod.name)

                terp = self.get_module_info(old_mod.name)
                if not terp or not terp.get('installable', True):
                    if old_mod.state != 'uninstallable':
                        self.write(cr, uid, old_mod.id, {'state': 'uninstallable'})
                    continue
                
                values = self.get_values_from_terp(terp)
                new_values = { }
                
                for key in values:
                    if getattr(old_mod, key) != ifustr(values[key]):
                        new_values[key] = ifustr(values[key])
                
                if new_values:
                    self.write(cr, uid, old_mod.id, new_values)
                
                old_depends = [ x.name for x in old_mod.dependencies_id ]
                old_depends.sort()
                new_depends = terp.get('depends', [])
                new_depends.sort()
                if old_depends != new_depends:
                    cr.execute('DELETE FROM ir_module_module_dependency '
                                'WHERE module_id = %s', (old_mod.id,), debug=self._debug)
                    self._update_dependencies(cr, uid, old_mod.id, new_depends)
        
                self._update_category(cr, uid, old_mod.id, terp.get('category', 'Uncategorized'),
                                old_cat=old_mod.category_id)

            else:
                # This module is no longer in the file tree
                if old_mod.state != 'uninstallable':
                    self.write(cr, uid, old_mod.id, {'state': 'uninstallable'})
                # TODO: clear dependencies or even module data, RFC

        # Now, we are left with names of modules that are not in the db,
        # the new modules:

        for mod_name in known_module_names:
            terp = self.get_module_info(mod_name)
            values = self.get_values_from_terp(terp)

            mod_path = addons.get_module_path(mod_name)
            # Addons shouldn't ever tell us names of non-existing modules
            assert mod_path, "No module path for %s" % mod_name
            if not terp or not terp.get('installable', True):
                continue

            values['state'] = 'uninstalled'
            values['name'] = mod_name
            id = self.create(cr, uid, values, context=context)
            res[1] += 1
            self._update_dependencies(cr, uid, id, terp.get('depends', []))
            self._update_category(cr, uid, id, terp.get('category', 'Uncategorized'), old_cat=False)

        return res

    def download(self, cr, uid, ids, download=True, context=None):
        res = []
        for mod in self.browse(cr, uid, ids, context=context):
            if not mod.url:
                continue
            match = re.search('-([a-zA-Z0-9\._-]+)(\.zip)', mod.url, re.I)
            version = '0'
            if match:
                version = match.group(1)
            if parse_version(mod.installed_version or '0') >= parse_version(version):
                continue
            res.append(mod.url)
            if not download:
                continue
            zipfile = urllib.urlopen(mod.url).read()
            fname = addons.get_module_path(str(mod.name)+'.zip', downloaded=True)
            try:
                fp = file(fname, 'wb')
                fp.write(zipfile)
                fp.close()
            except Exception:
                self.__logger.exception('Error when trying to create module '
                                        'file %s', fname)
                raise orm.except_orm(_('Error'), _('Can not create the module file:\n %s') % (fname,))
            terp = self.get_module_info(mod.name)
            self.write(cr, uid, mod.id, self.get_values_from_terp(terp))
            cr.execute('DELETE FROM ir_module_module_dependency ' \
                    'WHERE module_id = %s', (mod.id,), debug=self._debug)
            self._update_dependencies(cr, uid, mod.id, terp.get('depends',
                []))
            self._update_category(cr, uid, mod.id, terp.get('category',
                'Uncategorized'))
            # Import module
            zimp = zipimport.zipimporter(fname)
            zimp.load_module(mod.name)
        return res

    def _update_dependencies(self, cr, uid, id, depends=[]):
        for d in depends:
            cr.execute('INSERT INTO ir_module_module_dependency (module_id, name) values (%s, %s)', (id, d), debug=self._debug)

    def _update_category(self, cr, uid, id, category='Uncategorized', old_cat=None):
        if old_cat is None:
            old_cat = self.browse(cr, uid, id).category_id
        categs = category.split('/')
       
        if old_cat:
            old_ids = []
            while old_cat:
                old_ids.insert(0, old_cat.name)
                old_cat = old_cat.parent_id
                
            if old_ids == categs:
                return
                
        p_id = None
        while categs:
            if p_id is not None:
                cr.execute('SELECT id FROM ir_module_category WHERE name=%s AND parent_id=%s', (categs[0], p_id), debug=self._debug)
            else:
                cr.execute('SELECT id FROM ir_module_category WHERE name=%s AND parent_id IS NULL', (categs[0],), debug=self._debug)
            c_id = cr.fetchone()
            if not c_id:
                cr.execute('INSERT INTO ir_module_category (name, parent_id) VALUES (%s, %s) RETURNING id', (categs[0], p_id), debug=self._debug)
                c_id = cr.fetchone()[0]
            else:
                c_id = c_id[0]
            p_id = c_id
            categs = categs[1:]
        self.write(cr, uid, [id], {'category_id': p_id})

    def update_translations(self, cr, uid, ids, filter_lang=None, context=None):
        logger = logging.getLogger('i18n')
        if not filter_lang:
            pool = pooler.get_pool(cr.dbname)
            lang_obj = pool.get('res.lang')
            lang_ids = lang_obj.search(cr, uid, [('translatable', '=', True)])
            filter_lang = [lang.code for lang in lang_obj.browse(cr, uid, lang_ids)]
        elif not isinstance(filter_lang, (list, tuple)):
            filter_lang = [filter_lang]

        for mod in self.browse(cr, uid, ids):
            if mod.state != 'installed':
                continue
            modpath = addons.get_module_path(mod.name)
            if not modpath:
                # unable to find the module. we skip
                continue
            for lang in filter_lang:
                if len(lang) > 5:
                    raise osv.except_osv(_('Error'), _('You Can Not Load Translation For language Due To Invalid Language/Country Code'))
                iso_lang = tools.get_iso_codes(lang)
                f = addons.get_module_resource(mod.name, 'i18n', iso_lang + '.po')
                # Implementation notice: we must first search for the full name of
                # the language derivative, like "en_UK", and then the generic,
                # like "en".
                if (not f) and '_' in iso_lang:
                    f = addons.get_module_resource(mod.name, 'i18n', iso_lang.split('_')[0] + '.po')
                    iso_lang = iso_lang.split('_')[0]
                if f:
                    logger.info('module %s: loading translation file for language %s', mod.name, iso_lang)
                    tools.trans_load(cr.dbname, f, lang, verbose=False, context=context)
                else:
                    logger.warning('module %s: no translation for language %s', mod.name, iso_lang)

    def check(self, cr, uid, ids, context=None):
        logger = logging.getLogger('init')
        for mod in self.browse(cr, uid, ids, context=context):
            if not mod.description:
                logger.warn('module %s: description is empty !', mod.name)

            if not mod.certificate or not mod.certificate.isdigit():
                logger.info('module %s: no quality certificate', mod.name)
            else:
                val = long(mod.certificate[2:]) % 97 == 29
                if not val:
                    logger.critical('module %s: invalid quality certificate: %s', mod.name, mod.certificate)
                    raise osv.except_osv(_('Error'), _('Module %s: Invalid Quality Certificate') % (mod.name,))

    def list_web(self, cr, uid, context=None):
        """ list_web(cr, uid, context) -> [module_name]
        Lists all the currently installed modules with a web component.

        Returns a list of addon names.
        """
        return [
            module['name']
            for module in self.browse(cr, uid,
                self.search(cr, uid,
                    [('web', '=', True),
                     ('state', 'in', ['installed','to upgrade','to remove'])],
                    context=context),
                context=context)]
    def _web_dependencies(self, cr, uid, module, context=None):
        for dependency in module.dependencies_id:
            (parent,) = self.browse(cr, uid, self.search(cr, uid,
                [('name', '=', dependency.name)], context=context),
                                 context=context)
            if parent.web:
                yield parent.name
            else:
                self._web_dependencies(
                    cr, uid, parent, context=context)
    def get_web(self, cr, uid, names, context=None):
        """ get_web(cr, uid, [module_name], context) -> [{name, depends, content}]

        Returns the web content of all the named addons.

        The toplevel directory of the zipped content is called 'web',
        its final naming has to be managed by the client
        """
        mod_ids = self.search(cr, uid, [('name', 'in', names)], context=context)
        if not mod_ids:
            return []
        res = []
        for module in self.browse(cr, uid, mod_ids, context=context):
            web_dir = addons.get_module_resource(module.name, 'web')
            if not web_dir:
                continue
            res.append( {'name': module.name,
                    'depends': list(self._web_dependencies(
                            cr, uid, module, context=context)),
                    'content': addons.zip_directory(web_dir)
                        })

        self.__logger.debug('Sending web content of modules %s to web client', 
                    [ r['name'] for r in res])
        return res


module()

class module_dependency(osv.osv):
    _name = "ir.module.module.dependency"
    _description = "Module dependency"

    def _state(self, cr, uid, ids, name, args, context={}):
        result = {}
        mod_obj = self.pool.get('ir.module.module')
        for md in self.browse(cr, uid, ids):
            ids = mod_obj.search(cr, uid, [('name', '=', md.name)])
            if ids:
                result[md.id] = mod_obj.read(cr, uid, [ids[0]], ['state'])[0]['state']
            else:
                result[md.id] = 'unknown'
        return result

    _columns = {
        'name': fields.char('Name',  size=128, select=True),
        'module_id': fields.many2one('ir.module.module', 'Module', select=True, ondelete='cascade'),
        'state': fields.function(_state, method=True, type='selection', selection=[
            ('uninstallable','Uninstallable'),
            ('uninstalled','Not Installed'),
            ('installed','Installed'),
            ('to upgrade','To be upgraded'),
            ('to remove','To be removed'),
            ('to install','To be installed'),
            ('unknown', 'Unknown'),
            ], string='State', readonly=True, select=True),
    }
module_dependency()
