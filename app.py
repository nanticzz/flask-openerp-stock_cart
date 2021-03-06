#This file is part openerp-stock-cart app for Flask.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
import os
import ConfigParser
import erppeek
import bz2
import socket
from functools import wraps

from flask import Flask, render_template, request, jsonify, abort, session, redirect, url_for, flash
from flask.ext.babel import Babel, gettext as _
from flask.ext.wtf.html5 import IntegerField
from wtforms import Form, TextField, validators

from apphelp import get_description
from form import *
from defaultfilters import *


def get_config():
    '''Get values from cfg file'''
    conf_file = '%s/config.ini' % os.path.dirname(os.path.realpath(__file__))
    config = ConfigParser.ConfigParser()
    config.read(conf_file)

    results = {}
    for section in config.sections():
        results[section] = {}
        for option in config.options(section):
            results[section][option] = config.get(section, option)
    return results

def create_app(config=None):
    '''Create Flask APP'''
    cfg = get_config()
    app_name = cfg['flask']['app_name']
    app = Flask(app_name)
    app.config.from_pyfile(config)

    return app

def get_template(tpl):
    '''Get template'''
    return "%s/%s" % (app.config.get('TEMPLATE'), tpl)

def parse_setup(filename):
    globalsdict = {}  # put predefined things here
    localsdict = {}  # will be populated by executed script
    execfile(filename, globalsdict, localsdict)
    return localsdict

def get_lang():
    return app.config.get('LANGUAGE')

def erp_connect():
    '''OpenERP Connection'''
    server = app.config.get('OPENERP_SERVER')
    database = app.config.get('OPENERP_DATABASE')
    username = session['username']
    password = bz2.decompress(session['password'])
    try:
        Client = erppeek.Client(server, db=database, user=username, password=password)
    except socket.error:
        flash(_("Can't connect to ERP server. Check network-ports or ERP server was running."))
        abort(500)
    except:
        abort(500)
    return Client

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logged = session.get('logged_in', None)
        if not logged:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


conf_file = '%s/config.cfg' % os.path.dirname(os.path.realpath(__file__))
app = create_app(conf_file)
app.config['BABEL_DEFAULT_LOCALE'] = get_lang()
app.root_path = os.path.dirname(os.path.abspath(__file__))
babel = Babel(app)

# OpenERP models - access
MODELS_ACCESS = ({
    'stock.picking': 'write',
    'stock.cart': 'read',
    })

@app.errorhandler(404)
def page_not_found(e):
    return render_template(get_template('404.html')), 404

@app.errorhandler(500)
def server_error(e):
    return render_template(get_template('500.html')), 500

@app.route('/')
@login_required
def index():
    '''Dashboard'''
    cart = session.get('cart', None)
    if not cart:
        return redirect(url_for('cart'))

    return render_template(get_template('index.html'))

@app.route("/login", methods=["GET", "POST"])
def login():
    '''Login'''
    data = {}

    form = LoginForm()
    if form.validate_on_submit():
        username = request.form.get('username')
        password = bz2.compress(request.form.get('password'))
        session['username'] = username
        session['password'] = password

        Client = erp_connect()
        login = Client.login(username, bz2.decompress(password), app.config.get('OPENERP_DATABASE'))
        if login:
            access = True
            for key, value in MODELS_ACCESS.iteritems():
                if not Client.access(key, mode=value):
                    access = False
                    flash(_('Error: Not access in %(key)s - %(value)s' % { 'key': key, 'value': value} ))
            if access:
                session['logged_in'] = True
                flash(_('You were logged in.'))
                return redirect(url_for('index'))
        else:
            flash(_('Error: Invalid username %s or password' % session.get('username')))
        data['username'] = username

    return render_template(get_template('login.html'), form=form, data=data)

@app.route('/logout')
@login_required
def logout():
    '''Logout App'''
    Client = erp_connect()

    # Remove all stock.cart by user
    StockCart = Client.model('stock.cart')
    user_id = Client.search('res.users',[
                ('login', '=', session.get('username')),
                ])[0]
    carts = Client.search('stock.cart',[
                ('user_id', '=', user_id),
                ])
    for cart in carts:
        c = StockCart.get(cart)
        c.write({'user_id': None})

    # Remove all sessions
    session.pop('logged_in', None)

    session.pop('username', None)
    session.pop('password', None)
    session.pop('cart', None)
    session.pop('cart_name', None)

    flash(_('You were logged out.'))
    return redirect(url_for('login'))

@app.route('/cart', methods=["GET"])
@login_required
def cart():
    '''Select a stock cart by user'''
    Client = erp_connect()
    StockCart = Client.model('stock.cart')

    '''Drop currenty cart by user'''
    if session.get('cart'):
        cart_old = StockCart.get(int(session.get('cart')))
        cart_old.write({'user_id': None})
        session.pop('cart', None)
        session.pop('cart_name', None)

    '''Get cart id and add who working in stock.cart'''
    if request.method == 'GET':
        cart = request.args.get('cart', None)
        order = request.args.get('order', None)

        if cart:
            try:
                # Get Cart object from request.get
                id = int(cart)
                cart = StockCart.get(id)

                if not cart.user_id and cart.active:
                    #get user id
                    user_id = Client.search('res.users',[
                                ('login', '=', session.get('username')),
                                ])[0]

                    # Add new session values and log in stock.cart
                    session['cart'] = cart.id
                    session['cart_name'] = cart.name
                    session['cart_rows'] = cart.rows
                    session['cart_columns'] = cart.columns

                    cart.write({'user_id': user_id})
                    return redirect(url_for('index'))
                else:
                    if cart.user_id:
                        flash(_(u'Cart %(name)s is working by user %(user)s.', name=cart.name, user=cart.user_id))
                    else:
                        flash(_(u'Not find some cart by %(id)s.', id=cart))
            except:
                flash(_('Error: Cart ID not valid or empty'))

        if order:
            flash(_(u'Order products by: %(order)s.', order=order))
            session['order'] = order
    
    carts = StockCart.browse([('active', '=', True)])
    return render_template(get_template('cart.html'), carts=carts)

@app.route('/picking')
@login_required
def picking():
    '''Get all pickings and get info to make pickings'''
    cart = session.get('cart', None)
    order = session.get('order', 'product_location')
    if not cart:
        return redirect(url_for('cart'))

    Client = erp_connect()
    products, picking_grid = Client.execute('stock.picking', 'get_products_to_cart', cart, order)

    products_ean = []
    for product in products:
        if product['ean13']:
            products_ean.append(product)

    return render_template(get_template('picking.html'), products=products, products_ean=products_ean, grid=picking_grid)

@app.route('/send-move', methods=['PUT', 'POST'])
def send_move():
    values = {}
    for data in request.json:
        if data.get('name').split('-')[0] == 'ean':
            continue
        if data.get('name') and data.get('value'):
            values[data['name']] = data['value']

    Client = erp_connect()
    result = Client.execute('stock.move', 'set_cart_to_move', values)

    if not result:
        response = jsonify({'message': _(u'Error when process moves:qty %(values)s.', values=values)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/print-picking', methods=['PUT', 'POST'])
def print_picking():
    '''Print picking
    Get picking name and send to print
    ''' 
    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_print', [request.json])

    if not result:
        response = jsonify({'message': _(u'Error when print pickings %(pickings)s.', pickings=pickings)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/carrier-picking', methods=['PUT', 'POST'])
def carrier_picking():
    '''Carrier picking
    Get picking name and send to carrier
    ''' 
    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_carrier', [request.json])

    if not result:
        response = jsonify({'message': _(u'Error when send pickings %(pickings)s to carrier.', pickings=pickings)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/send-pickings', methods=['PUT', 'POST'])
def send_pickings():
    '''Finish process: Send pickings''' 
    cart = session.get('cart', None)
    pickings = []
    for data in request.json:
        if data.get('name'):
            pickings.append(data.get('name'))

    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_finish', cart, pickings)

    if not result:
        response = jsonify({'message': _(u'Error when process pickings %(pickings)s.', pickings=pickings)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/print-pickings', methods=['PUT', 'POST'])
def print_pickings():
    '''Print All pickings''' 
    pickings = []
    for data in request.json:
        if data.get('name'):
            pickings.append(data.get('name'))

    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_print', pickings)

    if not result:
        response = jsonify({'message': _(u'Error when print pickings %(pickings)s.', pickings=pickings)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/carrier-pickings', methods=['PUT', 'POST'])
def carrier_pickings():
    '''Carrier All pickings''' 
    pickings = []
    for data in request.json:
        if data.get('name'):
            pickings.append(data.get('name'))

    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_carrier', pickings)

    if not result:
        response = jsonify({'message': _(u'Error when delivery pickings %(pickings)s.', pickings=pickings)})
        response.status_code = 500
        return response
    return jsonify(result=True)

@app.route('/qty-pickings', methods=['PUT', 'POST'])
def qty_pickings():
    '''Get Qty from pickings
    ERP return dict {'Picking number': {'move':'qty'}}
    '''
    Client = erp_connect()
    result = Client.execute('stock.picking', 'stock_cart_qty', request.json)

    return jsonify(result=result)


class LocationForm(Form):
    """
    A form add location product
    """
    location = TextField(_('Location'), [validators.Required()], description=_('Location separated by " " (space):rack row case'))
    ean13 = IntegerField('EAN13', [validators.Required()])

    def validate(self):
        rv = Form.validate(self)
        if not self.location.data:
            return False
        if not self.ean13.data:
            return False
        return True


@app.route('/location', methods=['GET', 'POST'])
@login_required
def location():
    '''Product location'''
    form = LocationForm(request.form)

    return render_template(get_template('location.html'), form=form)

@app.route('/product-save-location', methods=['POST'])
@login_required
def product_save_location():
    '''Save location from EAN product'''
    result = {}

    values = {}
    for data in request.json:
        values[data['name']] = data['value']

    ean13 = values.get('ean13')
    location = values.get('location')

    Client = erp_connect()
    products = Client.search('product.product',['|',
            ('ean13', '=', ean13),
            ('ean13_ids.name', '=', ean13),
            ])
    if not products:
        result['message'] = _(u'Not found EAN13: %s' % ean13)
        result['color'] = 'red'
    else:
        Product = Client.model('product.product')
        p = Product.get(products[0])

        values = {}
        loc = location.split(' ')
        if len(loc) == 3:
            values['loc_rack'] = loc[0]
            values['loc_row'] = loc[1]
            values['loc_case'] = loc[2]
        if len(loc) == 2:
            values['loc_rack'] = loc[0]
            values['loc_row'] = loc[1]
        if len(loc) == 1:
            values['loc_rack'] = loc[0]
        p.write(values)
        result['message'] = _(u'Save location. EAN13 %s - %s' % (ean13, location))
        result['color'] = 'green'

    return jsonify(result)

@app.route('/product-get-location', methods=['POST'])
@login_required
def product_get_location():
    '''Get location from EAN product'''
    result = {}

    values = {}
    for data in request.json:
        values[data['name']] = data['value']

    ean13 = values.get('product-ean13')

    Client = erp_connect()
    products = Client.search('product.product',['|',
            ('ean13', '=', ean13),
            ('ean13_ids.name', '=', ean13),
            ])
    if not products:
        result['message'] = _(u'Not found EAN13: %s' % ean13)
        result['color'] = 'red'
    else:
        Product = Client.model('product.product')
        p = Product.get(products[0])
        location = []
        if p.loc_rack:
            location.append(p.loc_rack)
        if p.loc_row:
            location.append(p.loc_row)
        if p.loc_case:
            location.append(p.loc_case)

        if location:
            result['message'] = _(u'Location: %s' % ('-'.join(location)))
            result['color'] = 'green'
        else:
            result['message'] = _(u'Location is empty. Add a location EAN13 %s' % ean13)
            result['color'] = 'red'

    return jsonify(result)


class StockForm(Form):
    """
    A form add stock product
    """
    ean13 = IntegerField('EAN13', [validators.Required()])
    qty = IntegerField(_('Qty'), [validators.Required()], description=_('Add quantity available'))

    def validate(self):
        rv = Form.validate(self)
        if not self.ean13.data:
            return False
        if not self.qty.data:
            return False
        return True


@app.route('/stock', methods=['GET', 'POST'])
@login_required
def stock():
    '''Product Stock'''
    form = StockForm(request.form)

    return render_template(get_template('stock.html'), form=form)

@app.route('/stock-save', methods=['POST'])
@login_required
def stock_save():
    '''Save stock from EAN product'''
    result = {}

    values = {}
    for data in request.json:
        values[data['name']] = data['value']

    ean13 = values.get('ean13')
    qty = values.get('qty')

    try:
        qty = int(qty)
    except:
        result['message'] = _(u'Quantity %s is not numeric' % (qty))
        result['color'] = 'red'
        return jsonify(result)

    Client = erp_connect()
    products = Client.search('product.product',['|',
            ('ean13', '=', ean13),
            ('ean13_ids.name', '=', ean13),
            ])
    if not products:
        result['message'] = _(u'Not found EAN13: %s' % ean13)
        result['color'] = 'red'
    else:
        Product = Client.model('product.product')
        p = Product.get(products[0])

        Inventory = Client.model('stock.inventory')

        lines = {
            #~ 'location_id': 
            'product_id': p.id,
            'product_uom': p.uom_id.id,
            'product_qty': qty,
            }
        values = {
            'name': '[%s] %s' % (p.code, p.name),
            'inventory_line_id': [(0, 0, lines)]
            }
        inventory = Inventory.create(values)

        done = False
        confirm = Client.execute('stock.inventory', 'action_confirm', [inventory.id])
        if confirm:
            done = Client.execute('stock.inventory', 'action_done', [inventory.id])
        if done:
            result['message'] = _(u'Save quantity. EAN13: %s - Qty: %s' % (ean13, qty))
            result['color'] = 'green'
        else:
            result['message'] = _(u'Save quantity error. EAN13: %s' % (ean13))
            result['color'] = 'red'

    return jsonify(result)

@app.route('/product-get-stock', methods=['POST'])
@login_required
def product_get_stock():
    '''Get Stock from EAN product'''
    result = {}

    values = {}
    for data in request.json:
        values[data['name']] = data['value']

    ean13 = values.get('product-ean13')

    Client = erp_connect()
    products = Client.search('product.product',['|',
            ('ean13', '=', ean13),
            ('ean13_ids.name', '=', ean13),
            ])
    if not products:
        result['message'] = _(u'Not found EAN13: %s' % ean13)
        result['color'] = 'red'
    else:
        Product = Client.model('product.product')
        p = Product.get(products[0])
        location = []
        if p.loc_rack:
            location.append(p.loc_rack)
        if p.loc_row:
            location.append(p.loc_row)
        if p.loc_case:
            location.append(p.loc_case)

        if location:
            result['message'] = _(u'Location: %s' % ('-'.join(location)))
            result['color'] = 'green'
        else:
            result['message'] = _(u'Location is empty. Add a location EAN13 %s' % ean13)
            result['color'] = 'red'

        result['stock'] = _(u'Stock: %s' % p.qty_available)

    return jsonify(result)

@app.route('/find-product-ean', methods=['POST'])
@login_required
def find_product_ean():
    '''Find product by EAN'''
    result = False

    ean = request.json.get('ean') # EAN from id div
    ean13 = request.json.get('ean13')

    Client = erp_connect()
    products = Client.search('product.product',[
            ('ean13', '=', ean),
            ('ean13', '=', ean13),
            ])
    if not products:
        products = Client.search('product.product',[
                ('ean13', '=', ean),
                ('ean13_ids.name', '=', ean13),
                ])
    if products:
        result = True

    return jsonify(result=result)

@app.route('/help')
@login_required
def help():
    '''Help - Documentation'''
    lang = get_lang()
    description = get_description(lang)
    return render_template(get_template('help.html'), content=description)

if __name__ == "__main__":
    app.run()
