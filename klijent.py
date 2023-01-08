#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import spade
import time
import random
import asyncio
import sys
import uuid
from pprint import pprint
import json
from random import randint
from konfiguracija import IP_PROSODY, TRZISTE, TRZISTE_BASE, TRZISTE_QUOTE, KLIJENT_PROFIT_MARGIN


class Klijent(spade.agent.Agent):
    async def setup(self):
        self.starting_balance = {
            TRZISTE_BASE: 0,
            TRZISTE_QUOTE: 15000
        }
        self.balance = self.starting_balance.copy()
        self.aktivne_narudzbe = []
        self.cijene = {
            "buy": 0,
            "sell": 0
        }

        self.add_behaviour(self.PretplatiNaCijene())
        fsm = self.PonasanjeKA()
        fsm.add_state(name="StanjeProfita",
                      state=self.StanjeProfita(), initial=True)
        fsm.add_state(name="StanjeGubitka", state=self.StanjeGubitka())
        fsm.add_transition(source="StanjeProfita", dest="StanjeGubitka")
        fsm.add_transition(source="StanjeProfita", dest="StanjeProfita")
        fsm.add_transition(source="StanjeGubitka", dest="StanjeProfita")
        fsm.add_transition(source="StanjeGubitka", dest="StanjeGubitka")
        self.add_behaviour(fsm)

        primaj_executione = spade.template.Template()
        primaj_executione.set_metadata("ontology", "execution")
        self.add_behaviour(self.PrimajExecutione(), primaj_executione)

        primaj_cijene = spade.template.Template()
        primaj_cijene.set_metadata("ontology", "pretplata-cijene")
        self.add_behaviour(self.PrimajCijene(), primaj_cijene)

    async def daj_cijene(self):
        # Moze se desiti da je order book na prazan na jako kratko vrijeme
        # pa cemo cekati dok se ne popuni
        while True:
            sell = self.cijene["sell"]
            buy = self.cijene["buy"]
            if sell > 0 and buy > 0:
                break
            await asyncio.sleep(0.001)
        return [buy, sell]

    def pronadji_narudzbu(self, narudzba_id):
        for narudzba in self.aktivne_narudzbe:
            if narudzba["id"] == narudzba_id:
                return narudzba
        return None

    def ukloni_narudzbu(self, narudzba_id):
        for narudzba in self.aktivne_narudzbe:
            if narudzba["id"] == narudzba_id:
                self.aktivne_narudzbe.remove(narudzba)
                return True
        return False

    async def daj_stanje(self):
        trenutno_fiat = self.balance[TRZISTE_QUOTE]

        _, sell_price = await self.daj_cijene()
        trenutno_crypto_value = self.balance[TRZISTE_BASE] * sell_price
        return trenutno_fiat + trenutno_crypto_value

    async def isprintaj_stanje(self):
        print(
            f"Trenutan profit je {(await self.daj_stanje()) - self.starting_balance[TRZISTE_QUOTE]}.")

    async def stanje_je_profit(self):
        return await self.daj_stanje() >= self.starting_balance[TRZISTE_QUOTE]

    class PretplatiNaCijene(spade.behaviour.OneShotBehaviour):
        async def run(self):
            await self.send(spade.message.Message(
                to=f"knjiga_narudzbi@{IP_PROSODY}",
                body=self.agent.jid.localpart + "@" + self.agent.jid.domain,
                metadata={
                    "ontology": "pretplati-na-cijene",
                    "performative": "inform"
                })
            )
            print("Pretplacen na cijene")

    class PrimajCijene(spade.behaviour.CyclicBehaviour):
        async def run(self):
            p = await self.receive(timeout=100)
            if p:
                cijene = json.loads(p.body)
                self.agent.cijene = cijene

    class PrimajExecutione(spade.behaviour.CyclicBehaviour):
        async def run(self):
            p = await self.receive(timeout=100)
            if p:
                e = json.loads(p.body)
                n = self.agent.pronadji_narudzbu(
                    e["order_id"])
                if not n:
                    return
                print(f"Primio execution na {e['qty']} {n['base']}")
                # print(
                #     f'Narudzba za {n["side"]} {n["qty"]} {n["base"]} po cijeni {n["price"]} je izvrsena za {e["qty"]}.')
                # print("Novi balance:")
                base, quote = TRZISTE.split("-")
                if n["side"] == "buy":
                    self.agent.balance[base] += e["qty"]
                    self.agent.balance[quote] -= e["qty"] * \
                        e["price"]
                    # pprint(self.agent.balance)
                else:
                    self.agent.balance[base] -= e["qty"]
                    self.agent.balance[quote] += e["qty"] * \
                        e["price"]
                    # pprint(self.agent.balance)
                if n["qty"] == e["qty"]:
                    self.agent.ukloni_narudzbu(n["id"])

    class PonasanjeKA(spade.behaviour.FSMBehaviour):
        async def on_start(self):
            pass

        async def on_end(self):
            await self.agent.stop()

    class StanjeProfita(spade.behaviour.State):
        async def run(self):
            print("Stanje: StanjeProfita")
            narudzba = await self.generiraj_narudzbu()
            self.agent.aktivne_narudzbe.append(narudzba)
            await self.posalji_narudzbu(narudzba)
            print(
                f"{narudzba['side']} {narudzba['qty']} {narudzba['base']} po cijeni od {narudzba['price']} {narudzba['quote']} (vrijednost = {narudzba['price'] * narudzba['qty']})")

            for i in range(20):
                await asyncio.sleep(1)
                n = self.agent.pronadji_narudzbu(narudzba["id"])
                # ako je narudzba izvrsena, prekini
                if not n:
                    break

            # ako i dalje postoji nakon X sec, otkazi
            if n:
                await self.otkazi_narudzbu(n)

            await self.agent.isprintaj_stanje()

            if not await self.agent.stanje_je_profit():
                self.set_next_state("StanjeGubitka")
            else:
                self.set_next_state("StanjeProfita")

        async def generiraj_narudzbu(self):
            buy_price, sell_price = await self.agent.daj_cijene()

            crypto_value = self.agent.balance[TRZISTE_BASE] * \
                sell_price
            fiat_value = self.agent.balance[TRZISTE_QUOTE]

            if crypto_value > fiat_value:
                side = "sell"
                qty = random.uniform(
                    self.agent.balance[TRZISTE_BASE] / 4, self.agent.balance[TRZISTE_BASE] / 2)
                price = buy_price + \
                    buy_price * KLIJENT_PROFIT_MARGIN
            else:
                side = "buy"
                qty = random.uniform(
                    self.agent.balance[TRZISTE_QUOTE] / 4, self.agent.balance[TRZISTE_QUOTE] / 2) / sell_price
                price = sell_price - \
                    sell_price * KLIJENT_PROFIT_MARGIN

            narudzba = {
                "id": str(uuid.uuid4()),
                "klijent_jid": self.agent.jid.localpart + "@" + self.agent.jid.domain,
                "type": "limit",
                "side": side,
                "base": TRZISTE_BASE,
                "quote": TRZISTE_QUOTE,
                "qty": qty,
                "price": price,
            }

            return narudzba

        async def otkazi_narudzbu(self, n):
            narudzba = {
                "id": n["id"],
                "side": n["side"],
                "klijent_jid": self.agent.jid.localpart + "@" + self.agent.jid.domain,
            }

            p = spade.message.Message(
                to=f"knjiga_narudzbi@{IP_PROSODY}",
                body=json.dumps(narudzba),
                metadata={
                    "ontology": "otkazi",
                },
            )

            await self.send(p)

            print(f'Uklanjam prethodnu narudzbu jer nije izvrsena')
            self.agent.ukloni_narudzbu(n["id"])

        async def posalji_narudzbu(self, narudzba):
            p = spade.message.Message(
                to=f"knjiga_narudzbi@{IP_PROSODY}",
                body=json.dumps(narudzba),
                metadata={
                    "ontology": "naruci",
                    "performative": "inform"
                })

            await self.send(p)

    class StanjeGubitka(spade.behaviour.State):
        async def run(self):
            print("Stanje: StanjeGubitka")
            narudzba = await self.generiraj_narudzbu()
            self.agent.aktivne_narudzbe.append(narudzba)
            await self.posalji_narudzbu(narudzba)
            print(
                f"{narudzba['side']} {narudzba['qty']} {narudzba['base']} po cijeni od {narudzba['price']} {narudzba['quote']} (vrijednost = {narudzba['price'] * narudzba['qty']})")

            while True:
                await asyncio.sleep(1)
                n = self.agent.pronadji_narudzbu(narudzba["id"])
                # ako je narudzba izvrsena, prekini
                if not n:
                    break

            await self.agent.isprintaj_stanje()

            if not await self.agent.stanje_je_profit():
                self.set_next_state("StanjeGubitka")
            else:
                self.set_next_state("StanjeProfita")

        async def generiraj_narudzbu(self):
            buy_price, sell_price = await self.agent.daj_cijene()

            crypto_value = self.agent.balance[TRZISTE_BASE] * \
                sell_price
            fiat_value = self.agent.balance[TRZISTE_QUOTE]

            if crypto_value > fiat_value:
                side = "sell"
                qty = random.uniform(
                    self.agent.balance[TRZISTE_BASE] / 4, self.agent.balance[TRZISTE_BASE] / 2)
                price = buy_price + \
                    buy_price * KLIJENT_PROFIT_MARGIN
            else:
                side = "buy"
                qty = random.uniform(
                    self.agent.balance[TRZISTE_QUOTE] / 4, self.agent.balance[TRZISTE_QUOTE] / 2) / sell_price
                price = sell_price - \
                    sell_price * KLIJENT_PROFIT_MARGIN

            narudzba = {
                "id": str(uuid.uuid4()),
                "klijent_jid": self.agent.jid.localpart + "@" + self.agent.jid.domain,
                "type": "limit",
                "side": side,
                "base": TRZISTE_BASE,
                "quote": TRZISTE_QUOTE,
                "qty": qty,
                "price": price,
            }

            return narudzba

        async def posalji_narudzbu(self, narudzba):
            p = spade.message.Message(
                to=f"knjiga_narudzbi@{IP_PROSODY}",
                body=json.dumps(narudzba),
                metadata={
                    "ontology": "naruci",
                    "performative": "inform"
                })

            await self.send(p)


if __name__ == "__main__":
    i = sys.argv[1]
    klijent = Klijent(f"klijent{i}@{IP_PROSODY}", "tajna")
    klijent.start().result()

    while klijent.is_alive():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            klijent.stop()
            break
