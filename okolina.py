#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import spade
from random import randint, choice, uniform
from urllib.request import urlopen, Request
import json
import time
from datetime import datetime, timedelta
from konfiguracija import PERIOD_CIJENE, TRZISTE, IP_PROSODY, PROMJENA_CIJENE


class Okolina(spade.agent.Agent):
    async def setup(self):
        self.add_behaviour(self.DajCijenuGlobalnogTrzista())
        self.add_behaviour(self.SimulirajCijene(
            period=1, start_at=datetime.now() + timedelta(seconds=PERIOD_CIJENE)))
        self.add_behaviour(self.SaljiCijene(period=PERIOD_CIJENE))

    class DajCijenuGlobalnogTrzista(spade.behaviour.OneShotBehaviour):
        async def run(self):
            self.agent.cijena = self._daj_cijenu_vanjskog_trzista(TRZISTE)
            print(f"CIJENA GLOBALNOG TRZISTA {TRZISTE}: {self.agent.cijena}")

        def _daj_cijenu_vanjskog_trzista(self, trziste):
            httprequest = Request("https://api.globalblock.eu/ticker?once=true",
                                  headers={"Accept": "application/json"})
            with urlopen(httprequest) as response:
                cijene = json.loads(response.read().decode())
                bid = float(cijene[trziste]["highestBid"])
                ask = float(cijene[trziste]["lowestAsk"])
                return round((bid + ask) / 2, 2)

    class SimulirajCijene(spade.behaviour.PeriodicBehaviour):
        async def run(self):
            p = PROMJENA_CIJENE * self.agent.cijena
            self.agent.cijena = round(self.agent.cijena + uniform(-p, p), 2)
            print(f"SIMULIRANA CIJENA {TRZISTE}: {self.agent.cijena}")

    class SaljiCijene(spade.behaviour.PeriodicBehaviour):
        async def run(self):
            p = spade.message.Message(
                to=f"marketbot@{IP_PROSODY}",
                body=json.dumps({
                    "cijena": self.agent.cijena,
                    "trziste": TRZISTE
                }),
                metadata={
                    "ontology": "cijena",
                    "performative": "inform"
                }
            )
            await self.send(p)


if __name__ == "__main__":
    okolina = Okolina(f"okolina@{IP_PROSODY}", "tajna")
    okolina.start().result()

    while okolina.is_alive():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            okolina.stop()
            break
