from bw2data.database import DatabaseChooser
from bw2data.backends.peewee import SQLiteBackend, ActivityDataset, ExchangeDataset
from tqdm import tqdm


def extract_activity(proxy):
    """Get data in Wurst internal format for an ``ActivityDataset``"""
    assert isinstance(proxy, ActivityDataset)

    return {
        'classifications': proxy.data.get('classifications', []),
        'comment': proxy.data.get('comment', ''),
        'location': proxy.location,
        'database': proxy.database,
        'code': proxy.code,
        'name': proxy.name,
        'reference product': proxy.product,
        'unit': proxy.data.get('unit', ''),
        'exchanges': []
    }


def extract_exchange(proxy):
    """Get data in Wurtst internal format for an ``ExchangeDataset``"""
    assert isinstance(proxy, ExchangeDataset)

    uncertainty_fields = ('uncertainty type', 'loc', 'scale', 'shape',
                          'minimum', 'maximum', 'amount', 'pedigree')
    data = {key: proxy.data.get(key) for key in uncertainty_fields}
    data['type'] = proxy.type
    data['production volume'] = proxy.data.get("production volume")
    data['input'] = (proxy.input_database, proxy.input_code)
    data['output'] = (proxy.output_database, proxy.output_code)
    return data


def add_exchanges_to_consumers(activities, exchange_qs):
    """Retrieve exchanges from database, and add to activities.

    Assumes that activities are single output, and that the exchange code is the same as the activity code. This assumption is valid for ecoinvent 3.3 cutoff imported into Brightway2."""
    lookup = {(o['database'], o['code']): o for o in activities}

    with tqdm(total=exchange_qs.count()) as pbar:
        for i, exc in enumerate(exchange_qs):
            exc = extract_exchange(exc)
            output = tuple(exc.pop('output'))
            lookup[output]['exchanges'].append(exc)
            pbar.update(1)
    return activities


def add_input_info_for_indigenous_exchanges(activities, names):
    """Add details on exchange inputs if these activities are already available"""
    names = set(names)
    lookup = {(o['database'], o['code']): o for o in activities}

    for ds in activities:
        for exc in ds['exchanges']:
            if 'input' not in exc or exc['input'][0] not in names:
                continue
            obj = lookup[exc['input']]
            exc['product'] = obj['reference product']
            exc['activity'] = obj['name']
            exc['unit'] = obj['unit']
            exc['location'] = obj['location']
            if exc['type'] == 'biosphere':
                exc['categories'] = obj['categories']
            exc.pop('input')


def add_input_info_for_external_exchanges(activities, names):
    """Add details on exchange inputs from other databases"""
    names = set(names)
    cache = {}

    for ds in tqdm(activities):
        for exc in ds['exchanges']:
            if 'input' not in exc or exc['input'][0] in names:
                continue
            if exc['input'] not in cache:
                cache[exc['input']] = ActivityDataset.get(
                    ActivityDataset.database == exc['input'][0],
                    ActivityDataset.code == exc['input'][1],
                )
            obj = cache[exc['input']]
            exc['activity'] = obj.name
            exc['product'] = obj.product
            exc['unit'] = obj.data['unit']
            exc['location'] = obj.location
            if exc['type'] == 'biosphere':
                exc['categories'] = obj.data['categories']


def extract_brightway2_databases(database_names):
    """Extract a Brightway2 SQLiteBackend database to the Wurst internal format"""
    ERROR = "Must pass list of database names"
    assert isinstance(database_names, (list, tuple)), ERROR

    databases = [DatabaseChooser(name) for name in database_names]
    ERROR = "Wrong type of database object (must be SQLiteBackend)"
    assert all(isinstance(obj, SQLiteBackend) for obj in databases), ERROR

    # Construct generators for both activities and exchanges
    # Need to be clever to minimize copying and memory use
    activity_qs = ActivityDataset.select().where(ActivityDataset.database << database_names)
    exchange_qs = ExchangeDataset.select().where(ExchangeDataset.output_database << database_names)

    # Retrieve all activity data
    print("Getting activity data")
    activities = [extract_activity(o) for o in tqdm(activity_qs)]
    # Add each exchange to the activity list of exchanges
    print("Adding exchange data to activities")
    add_exchanges_to_consumers(activities, exchange_qs)
    # Add details on exchanges which come from our databases
    print("Filling out exchange data")
    add_input_info_for_indigenous_exchanges(activities, database_names)
    add_input_info_for_external_exchanges(activities, database_names)
    return activities