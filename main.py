import time
import os
from datetime import datetime
from dotenv import load_dotenv

import dateutil.parser

import requests

load_dotenv()

# Configure Sentry
try:
    SENTRY_URL = os.environ["SENTRY_DSN"]

    import sentry_sdk
    sentry_sdk.init(SENTRY_URL)

except KeyError as e:
    print("SENTRY_DSN not found in environment, not configuring Sentry")
    pass # Ignore sentry initilization errors

# Configure Discord
try:
    DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
    if len(DISCORD_WEBHOOK) < 5:
        raise KeyError
except KeyError as e:
    raise Exception("DISCORD_WEBHOOK envar not found! You must set a DISCORD_WEBHOOK for things to work properly.")

CONTRACT = 'mainnet/KT1WZ1HJyx5wPt96ZTjtWPotoPUk7pXNPfT2'
# CONTRACT = 'florencenet/KT1E3aVbNwX5AwpSQ151dp3Qg4Wf9mGEs3ex'

KNOWN_CONTRACTS = {
    'KT1E3aVbNwX5AwpSQ151dp3Qg4Wf9mGEs3ex': "The Kolibri DAO"
}

vote_map = {
    0: "YAY",
    1: "NAY",
    2: "ABSTAIN"
}

def send_discord(payload):
    print("Submitting webhook...")
    response = requests.post(DISCORD_WEBHOOK, json=payload)
    response.raise_for_status()
    if int(response.headers['x-ratelimit-remaining']) == 0:
        rate_limit_reset = float(response.headers['x-ratelimit-reset-after']) + 1
        print("Waiting for discord rate limits...({} sec)".format(rate_limit_reset))
        time.sleep(rate_limit_reset)

    time.sleep(1)

    return response

def fetch_all_history():
    operations = []

    last_id = None

    while True:
        print("Looking back at id {}".format(last_id))
        params = {
            'status': 'applied',
            'entrypoints': 'vote,propose,executeTimelock,endVoting,cancelTimelock',
            # 'with_storage_diff': True # TODO: Parse storage diff to see `endVoting` outcome?
        }

        if last_id is not None:
            params['last_id'] = last_id

        response = requests.get(
            'https://api.better-call.dev/v1/contract/{}/operations'.format(CONTRACT),
            params=params
        )

        applied_ops = response.json()

        operations += applied_ops['operations']

        if 'last_id' not in applied_ops:
            break

        last_id = applied_ops['last_id']

    return operations

def fetch_contract_activity(since=None):
    params = {
        'status': 'applied',
        'entrypoints': 'vote,propose,executeTimelock,endVoting,cancelTimelock'
    }

    if since is not None:
        params['from'] = since

    response = requests.get(
        'https://api.better-call.dev/v1/contract/{}/operations'.format(CONTRACT),
        params=params
    )

    applied_ops = response.json()

    return applied_ops

def parse_operations_to_map(operations):
    op_map = {}

    for op in operations:
        print(op['counter'])
        if op['counter'] not in op_map:
            op_map[op['counter']] = [op]
        else:
            op_map[op['counter']].append(op)

    return op_map

def shorten_address(address):
    return address[:5] + "..." + address[-5:]

def handle_vote_operation(operations):
    vote_call = find_op(operations, 'vote')
    vote_value = int(vote_call['parameters'][0]['value'])
    voter = vote_call['source']

    vote_callback_call = find_op(operations, 'voteCallback')

    vote_amount = "{:,.2f}".format(
        int(vote_callback_call['parameters'][0]['children'][2]['value']) / (10 ** 18)
    )

    voter_link = '**[{}](<https://tzkt.io/{}>)**'.format(
        shorten_address(voter),
        voter
    )

    if vote_value == 0:
        formatted_vote = '<:blobyes:883220230896242718> **YAY**'
    elif vote_value == 1:
        formatted_vote = '<:blobno:883220231101763604> **NAY**'
    else:
        formatted_vote = '<:shrug:812037587908034590> **ABSTAIN**'

    tx_link = 'https://better-call.dev/mainnet/opg/{}'.format(vote_call['hash'])

    payload = {
        "content": ":ballot_box: {} voted {} with **{} kDAO** | **[TX](<{}>)**".format(
            voter_link,
            formatted_vote,
            vote_amount,
            tx_link
        )
    }

    send_discord(payload)

def handle_propose_operation(operations):
    propose_call = find_op(operations, 'propose')
    proposer_address = propose_call['source']
    proposal_title = propose_call['parameters'][0]['children'][0]['value']
    proposal_description_link = propose_call['parameters'][0]['children'][1]['value']
    proposal_lambda = propose_call['parameters'][0]['children'][3]['value']

    address_link = '**[{}](https://tzkt.io/{})**'.format(
        shorten_address(proposer_address),
        proposer_address
    )

    payload = {
      "content": ":office_worker: :scales: {} submitted a new proposal to the DAO! **[Link](https://governance.kolibri.finance)**".format(address_link),
      "embeds": [
        {
          "color": 4111763,
          "fields": [
            {
              "name": "Title",
              "value": proposal_title
            },
            {
              "name": "Description",
              "value": "[Link To Description]({})".format(proposal_description_link)
            },
            {
              "name": "Lambda",
              "value": "```{}```".format(proposal_lambda)
            }
          ],
          "thumbnail": {
            "url": "https://services.tzkt.io/v1/avatars/{}".format(proposer_address)
          }
        }
      ]
    }

    send_discord(payload)

def handle_execute_timelock_operation(operations):
    non_execute_operations = []

    for operation in operations:
        if operation['entrypoint'] != 'executeTimelock':
            non_execute_operations.append(operation)

    formatted_operations = []

    for operation in non_execute_operations:
        formatted_operations.append(
            "Called `%{}` on [{}](<https://better-call.dev/mainnet/{}/operations>)".format(
                operation['entrypoint'],
                KNOWN_CONTRACTS.get(operation['destination'], operation['destination']),
                operation['destination']
            )
        )

    execute_call = find_op(operations, 'executeTimelock')
    executor = execute_call['source']

    payload = {
        "content": ':timer_clock:  **[{}](https://tzkt.io/{})** Executed the proposal in the Kolibri DAO timelock!'.format(
            shorten_address(executor),
            executor
        ),
        "embeds": [{
            "title": "Executed Operations",
            "description": '\n'.join(formatted_operations),
            "color": 4111763
        }]
    }

    send_discord(payload)

def handle_end_voting_operation(operations):
    end_voting_call = find_op(operations, 'endVoting')
    ender = end_voting_call['source']
    # transfer_call = find_op(operations, 'transfer')

    address_link = '**[{}](<https://tzkt.io/{}>)**'.format(
        shorten_address(ender),
        ender
    )

    payload = {
        'content': ':lock: {} Closed voting (if things passed, they moved to the timelock and escrow was returned) **[TX](<https://better-call.dev/mainnet/opg/{}>)**'.format(
            address_link,
            end_voting_call['hash']
        )
    }

    send_discord(payload)

def handle_new_operations(operations):
    op_map = parse_operations_to_map(operations)

    for op_id, operations in op_map.items():
        entrypoints = set([x['entrypoint'] for x in operations])

        if 'vote' in entrypoints and 'voteCallback' in entrypoints:
            handle_vote_operation(operations)
        elif 'propose' in entrypoints and 'transfer' in entrypoints:
            handle_propose_operation(operations)
        elif 'executeTimelock' in entrypoints:
            handle_execute_timelock_operation(operations)
        elif 'endVoting' in entrypoints:
            handle_end_voting_operation(operations)
        else:
            print("Unknown operation", entrypoints)

def latest_timestamp_from_operations(operations):
    initial_event_timestamp = operations[0]['timestamp']
    initial_event_datetime = dateutil.parser.parse(initial_event_timestamp)
    latest_event_timestamp = int(initial_event_datetime.timestamp()) * 1000

    return latest_event_timestamp

def find_op(ops, entrypoint):
    return next(op for op in ops if op['entrypoint'] == entrypoint)

def watch_for_changes():
    bcd_payload = fetch_contract_activity()

    latest_event_timestamp = latest_timestamp_from_operations(bcd_payload['operations'])

    while True:
        search_timestamp = latest_event_timestamp + 1000  # Add a second to only look at future events

        new_activity = fetch_contract_activity(since=search_timestamp)

        new_operations = new_activity['operations']

        if len(new_operations) != 0:
            handle_new_operations(new_operations)
            latest_event_timestamp = latest_timestamp_from_operations(new_operations)
        else:
            print("No new activity, looping...")
            time.sleep(30)


if __name__ == "__main__":
    watch_for_changes()

    # all_operations = fetch_all_history()[::-1]
    # handle_new_operations(all_operations)

