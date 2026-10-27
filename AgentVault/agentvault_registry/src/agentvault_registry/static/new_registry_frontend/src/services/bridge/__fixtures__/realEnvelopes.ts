/**
 * services/bridge/__fixtures__/realEnvelopes.ts
 *
 * REAL websocket envelopes, captured verbatim from the live frame-c origin on
 * 2026-08-19T00:41:50.286Z (393 messages, 14 distinct types; capture script
 * `scratchpad/capture_ws_envelopes.mjs`).
 *
 * WHY THIS FILE EXISTS. The P1 grammar suite was written against envelopes I
 * invented from event TYPE NAMES. It passed 57/57 while the grammar could not
 * read the party out of a single real transfer on this network, because the
 * real payloads use a bare `from` / `to` that no invented fixture contained.
 * Tests written from imagination measure imagination.
 *
 * DO NOT hand-edit these payloads. Re-capture them.
 */
export const REAL_ENVELOPES = {
  "TokensTransferred": {
    "type": "event",
    "event": {
      "id": "0e8caee7-6909-400b-931d-8e4d4240c75c",
      "event_type": "TokensTransferred",
      "aggregate_id": "did:theprotocol:16968217-03a0-e909-5026",
      "aggregate_type": "Agent",
      "data": {
        "to": "did:theprotocol:5c79404f-e7ca-7f0d-2ad6",
        "from": "did:theprotocol:16968217-03a0-e909-5026",
        "memo": "cross_registry:fxroute:9d1d452d-fc6a-4ff1-b6b8-dc077de207f4:egress",
        "amount": "32.665148",
        "transaction_id": "1cabb58e-3083-4a03-af96-2c2e493625f5"
      },
      "timestamp": "2026-08-19T00:41:09.139973+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "FxSwapSettled": {
    "type": "event",
    "event": {
      "id": "ec391200-a89e-40dd-9514-512d5969979e",
      "event_type": "FxSwapSettled",
      "aggregate_id": "did:theprotocol:d2483510-9b75-ddf1-7ed1",
      "aggregate_type": "Agent",
      "data": {
        "to": "did:theprotocol:agora-gateway-jday",
        "fee": "0.458638",
        "from": "did:theprotocol:d2483510-9b75-ddf1-7ed1",
        "rate": "0.8430393598035123591432666924",
        "swap_id": "e8dba8ca-3236-4c3f-bd5b-9a6d27c02fda",
        "dest_teg": "teg-layer-frame-b",
        "amount_in": "108.805827312000000000",
        "amount_out": "91.268957",
        "dest_frame": "frame-b.theprotocol.cloud",
        "source_teg": "teg-layer-a",
        "source_frame": "agentvault.com",
        "dest_currency": "JDAY",
        "source_currency": "AVT"
      },
      "timestamp": "2026-08-19T00:40:49.813541+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "FxRouteSettled": {
    "type": "event",
    "event": {
      "id": "a723c5a4-0f65-4b03-99c1-c643c66ecea6",
      "event_type": "FxRouteSettled",
      "aggregate_id": "did:theprotocol:agora-gateway-bvt",
      "aggregate_type": "Agent",
      "data": {
        "to": "did:theprotocol:dd85a5ff-2d6a-3641-e466",
        "from": "did:theprotocol:agora-gateway-bvt",
        "hops": [
          {
            "ccy": "BVT->JDAY",
            "role": "fxcore",
            "event": "FxSwapSettled",
            "frame": "BVT",
            "swap_id": "cec19190-e95b-45ce-86d5-793c2fd0d7cc",
            "credited": "80.788181",
            "amount_in": "107.580000000000000000"
          },
          {
            "ccy": "JDAY",
            "tid": "480859c3-ae93-4e61-af12-e11f5b0c34e1",
            "role": "egress",
            "event": "TokensTransferred",
            "frame": "JDAY",
            "credited": "80.384240",
            "receiver": "did:theprotocol:dd85a5ff-2d6a-3641-e466",
            "amount_in": "80.788181"
          }
        ],
        "status": "settled",
        "gateway": "did:theprotocol:065e2052-5341-2dd2-3422",
        "route_id": "e509cd1a-8023-4b31-9ec1-d2d7cea32676",
        "amount_in": "107.580000000000000000",
        "amount_out": "80.384240",
        "source_frame": "frame-c.theprotocol.cloud",
        "dest_currency": "JDAY",
        "source_currency": "BVT",
        "origin_agent_spiffe": ""
      },
      "timestamp": "2026-08-19T00:41:02.714897+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "TransactionFeeCollected": {
    "type": "event",
    "event": {
      "id": "4f562b35-e6ed-48c5-8f09-adfd847a1ec8",
      "event_type": "TransactionFeeCollected",
      "aggregate_id": "did:theprotocol:16968217-03a0-e909-5026",
      "aggregate_type": "Agent",
      "data": {
        "to": "teg:system:fee_collector",
        "from": "did:theprotocol:5c79404f-e7ca-7f0d-2ad6",
        "fee_type": "cross_registry_transfer",
        "fee_amount": "0.163326",
        "net_credited": "32.501822",
        "transaction_id": "1cabb58e-3083-4a03-af96-2c2e493625f5",
        "original_amount": "32.665148"
      },
      "timestamp": "2026-08-19T00:41:09.139992+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "CrossRegistryTransferCompleted": {
    "type": "event",
    "event": {
      "id": "dabd979f-9eb1-4b71-a680-718d7bcfbc44",
      "event_type": "CrossRegistryTransferCompleted",
      "aggregate_id": "did:theprotocol:16968217-03a0-e909-5026",
      "aggregate_type": "Agent",
      "data": {
        "to": "did:theprotocol:5c79404f-e7ca-7f0d-2ad6",
        "from": "did:theprotocol:16968217-03a0-e909-5026",
        "amount": "32.665148",
        "source_teg": "teg-layer-a",
        "target_teg": "teg-layer-op-london",
        "transfer_id": "1cabb58e-3083-4a03-af96-2c2e493625f5"
      },
      "timestamp": "2026-08-19T00:41:09.139986+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "CrossFrameTransferInitiated": {
    "type": "event",
    "event": {
      "id": "ba7e50b0-bcdc-4267-a5c9-88023e5cc9cf",
      "event_type": "CrossFrameTransferInitiated",
      "aggregate_id": "did:theprotocol:f89df4b2-a12d-9bd0-691b",
      "data": {
        "transfer_id": "f75631f2-e102-49a9-b855-a6ebfbafe456",
        "sender_did": "did:theprotocol:f89df4b2-a12d-9bd0-691b",
        "receiver_did": "did:theprotocol:d8f8b4b5-7d5e-3feb-2101",
        "source_frame": "agentvault.com",
        "target_frame": "agentvault.com",
        "source_teg": "teg-op-paris",
        "target_teg": "teg-layer-op-london",
        "amount": "1.000000000000000000",
        "memo": "canary-paris->london:intra-d9252139ff"
      },
      "timestamp": "2026-08-19T00:41:18.780031+00:00",
      "version": 1
    }
  },
  "CrossFrameTransferSettled": {
    "type": "event",
    "event": {
      "id": "232715bc-e51f-4484-bea9-ea27b931ebcf",
      "event_type": "CrossFrameTransferSettled",
      "aggregate_id": "did:theprotocol:f89df4b2-a12d-9bd0-691b",
      "data": {
        "transfer_id": "f75631f2-e102-49a9-b855-a6ebfbafe456",
        "transaction_id": "f75631f2-e102-49a9-b855-a6ebfbafe456",
        "sender_did": "did:theprotocol:f89df4b2-a12d-9bd0-691b",
        "receiver_did": "did:theprotocol:d8f8b4b5-7d5e-3feb-2101",
        "source_frame": "agentvault.com",
        "target_frame": "agentvault.com",
        "amount": "1.000000000000000000",
        "memo": "canary-paris->london:intra-d9252139ff"
      },
      "timestamp": "2026-08-19T00:41:19.113054+00:00",
      "version": 1
    }
  },
  "ExchangeTradeExecuted": {
    "type": "event",
    "event": {
      "id": "ad4026d1-a0c3-4724-a876-c728316db009",
      "event_type": "ExchangeTradeExecuted",
      "aggregate_id": "e758cc80-a22f-4cd9-8ec9-e4cdd9b513f8",
      "aggregate_type": "ExchangeListing",
      "data": {
        "qty": "3",
        "seq": "972480",
        "price": "57.500000000000000000",
        "symbol": "GRLD",
        "currency": "AVT",
        "notional": "172.500000000000000000",
        "trade_id": "4783a947-d0bb-4b61-b8f4-74283c287e2e",
        "buyer_did": "did:theprotocol:0c7218a2-d70d-be17-4877",
        "seller_did": "did:theprotocol:org-grld-treasury"
      },
      "timestamp": "2026-08-19T00:41:08.611403+00:00",
      "version": 1,
      "source_service": "registry"
    }
  },
  "LedgerBalanceChanged": {
    "type": "event",
    "event": {
      "id": "1258d9df-b485-458f-a998-449fc073ebcc",
      "event_type": "LedgerBalanceChanged",
      "aggregate_id": "ledger-tx-teg-layer-a-58948238",
      "aggregate_type": "Ledger",
      "data": {
        "net": "0E-18",
        "kind": "unknown",
        "txid": 58948238,
        "frame": "teg-layer-a",
        "entries": [
          {
            "agent_did": "did:theprotocol:1da8b865-56b3-35b9-5b2d",
            "delta_liquid": "1.719154000000000000",
            "delta_staked": "0"
          },
          {
            "agent_did": "did:theprotocol:teg_system_fx_reserve",
            "delta_liquid": "-1.719154000000000000",
            "delta_staked": "0"
          }
        ]
      },
      "timestamp": "2026-08-19T00:40:46.248131+00:00",
      "version": 1,
      "source_service": "teg-balance-outbox"
    }
  },
  "CrossTEGStaleSwept": {
    "type": "event",
    "event": {
      "id": "d32473fd-1acd-4996-afdb-4f78b741d5d6",
      "event_type": "CrossTEGStaleSwept",
      "aggregate_id": "stale-sweep:teg-op-newyork",
      "data": {
        "swept": 1,
        "remaining": 0,
        "age_hours": 24,
        "batch_limit": 2000,
        "teg_id": "teg-op-newyork",
        "sweeper_worker": "9f9a635e904d-13-8596ef"
      },
      "timestamp": "2026-08-19T00:41:31.500597+00:00",
      "version": 1
    }
  },
  "HagridGiniSnapshot": {
    "type": "event",
    "event": {
      "id": "e59dde78-3cde-4071-b3e9-f8e25a1df607",
      "event_type": "HagridGiniSnapshot",
      "aggregate_id": "hagrid:gini",
      "data": {
        "gini": 0.991524,
        "active_agents": 6936,
        "top1_share": 0.861172,
        "top10_share": 0.601043,
        "state_label": "feudal",
        "frames": [
          {
            "id": "A",
            "currency": "AVT",
            "gini": 0.986231,
            "active": 2542,
            "supply_avt": 728141137.07243
          },
          {
            "id": "B",
            "currency": "JDAY",
            "gini": 0.992973,
            "active": 2479,
            "supply_avt": 1261188489.230516
          },
          {
            "id": "C",
            "currency": "BVT",
            "gini": 0.986232,
            "active": 1918,
            "supply_avt": 210723870.544618
          }
        ],
        "fx_avt_per_bvt": 0.89526,
        "fx_corridor_volume_avt": 283926.5475
      },
      "timestamp": "2026-08-19T00:41:18.837813+00:00",
      "version": 1
    }
  },
  "HagridConservation": {
    "type": "event",
    "event": {
      "id": "1cb87d79-9760-4e0b-823a-6e00a78da2d0",
      "event_type": "HagridConservation",
      "aggregate_id": "did:theprotocol:4397493c-3d89-22d6-5001",
      "data": {
        "word": "leak.",
        "total_negative_accounts": 220,
        "frames": [
          {
            "frame": "A",
            "negative": 79,
            "drift": 709544.580002,
            "transit": 2498.041432
          },
          {
            "frame": "B",
            "negative": 100,
            "drift": 12914.827499,
            "transit": 3541.427
          },
          {
            "frame": "C",
            "negative": 41,
            "drift": 2018987.387041,
            "transit": 1162774.234626
          }
        ],
        "computed_at": "2026-08-19T00:41:27.310451+00:00"
      },
      "timestamp": "2026-08-19T00:41:27.317872+00:00",
      "version": 1
    }
  }
} as const

export type RealEventType = keyof typeof REAL_ENVELOPES
