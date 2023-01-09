#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import spade
import time
import asyncio
from konfiguracija import IP_PROSODY, MARKET_BOT_MAINTAIN_VALUE, TRZISTE, MARKET_BOT_PROFIT_MARGIN, MARKET_BOT_MIN_PROFIT_MARGIN, MARKET_BOT_MAX_PROFIT_MARGIN
import json
import uuid
import random
from pprint import pprint


class MarketBot(spade.agent.Agent):
    buy_narudzbe = []
    sell_narudzbe = []

    async def setup(self):
        template = spade.template.Template()
        template.set_metadata("ontology", "cijena")
        self.add_behaviour(self.OdrzavajLikvidnost(period=1), template)

    def sell_value(self):
        return sum([n["qty"] * n["price"] for n in self.sell_narudzbe])

    def buy_value(self):
        return sum([n["qty"] * n["price"] for n in self.buy_narudzbe])

    def za_uklonit_iz_prodaje(self, cijena):
        za_uklonit = []
        # primjer: zeli se profit od 300 USDT
        minimalni_profit = MARKET_BOT_MIN_PROFIT_MARGIN * cijena
        maksimalni_profit = MARKET_BOT_MAX_PROFIT_MARGIN * cijena
        for n in self.sell_narudzbe:
            # order["price"] je 16 000, a trenutna cijena je 15 800
            # znaci pokusava se prodat za 200 USDT vise od trenutne cijene
            # mi zelimo barem 300 (to je minimalni profit), pa ce se ova narudzba
            # otkazati
            trenutni_profit = n["price"] - cijena
            if trenutni_profit < minimalni_profit or trenutni_profit > maksimalni_profit:
                za_uklonit.append(n)
        return za_uklonit

    def za_uklonit_iz_kupnje(self, cijena):
        za_uklonit = []
        # primjer: zeli se profit od 300 USDT
        minimalni_profit = MARKET_BOT_MIN_PROFIT_MARGIN * cijena
        maksimalni_profit = MARKET_BOT_MAX_PROFIT_MARGIN * cijena
        for n in self.buy_narudzbe:
            # order["price"] je 16 000, a trenutna globalna cijena je 16 200
            # znaci pokusava se kupit za 200 USDT manje od trenutne cijene na mjenjacnici
            # mi zelimo kupiti po profitu od barem 300 USDT (to je minimalni profit),
            # pa ce se ova narudzba otkazati
            trenutni_profit = cijena - n["price"]
            if trenutni_profit < minimalni_profit or trenutni_profit > maksimalni_profit:
                za_uklonit.append(n)
        return za_uklonit

    class OdrzavajLikvidnost(spade.behaviour.PeriodicBehaviour):
        async def run(self):
            p = await self.receive(timeout=1)
            if p:
                cijena = json.loads(p.body)["cijena"]

                za_uklonit_iz_prodaje = self.agent.za_uklonit_iz_prodaje(
                    cijena)
                za_uklonit_iz_kupnje = self.agent.za_uklonit_iz_kupnje(cijena)
                if za_uklonit_iz_prodaje or za_uklonit_iz_kupnje:
                    await self.ukloni_neprofitablilne(za_uklonit_iz_prodaje + za_uklonit_iz_kupnje)

                # izracunaj value ordera koji su na nasoj mjenjacnici
                buy_value = self.agent.buy_value()
                sell_value = self.agent.sell_value()

                # ako je value svih buy ili sell ordera zbrojeno manji od MARKET_BOT_MAINTAIN_VALUE, naruci
                # npr ako je MARKET_BOT_MAINTAIN_VALUE 100 000, to znaci da
                # treba postojati 100 000 USDT vrijednosti narudzbi na mjenjacnici kako bi bilo likvidnosti
                profit_margin = MARKET_BOT_PROFIT_MARGIN * cijena
                # 5 USDT je tolerancija
                if (buy_value + 5) < MARKET_BOT_MAINTAIN_VALUE:
                    # treba kupiti onoliko vrijednosti (U USDT) koliko nam nedostaje
                    to_buy = MARKET_BOT_MAINTAIN_VALUE - buy_value
                    # zelimo prodati po nizoj cijeni
                    profit_price = cijena - profit_margin
                    qty_to_buy = to_buy / profit_price
                    print(f"Kupujem {qty_to_buy} po cijeni od {profit_price}")
                    await self.naruci(side="buy", qty=qty_to_buy, price=profit_price)
                if (sell_value + 5) < MARKET_BOT_MAINTAIN_VALUE:
                    # treba prodati onoliko vrijednosti (U USDT) koliko nam nedostaje
                    to_sell = MARKET_BOT_MAINTAIN_VALUE - sell_value
                    # zelimo prodati po visoj cijeni
                    profit_price = cijena + profit_margin
                    qty_to_sell = to_sell / profit_price
                    print(
                        f"Prodajem {qty_to_sell} po cijeni od {profit_price}")
                    await self.naruci(side="sell", qty=qty_to_sell, price=profit_price)
            else:
                raise Exception("Nema cijene")

        async def ukloni_neprofitablilne(self, za_uklonit):
            for n in za_uklonit:
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

                print(
                    f'Uklanjam {n["side"]} {round(n["qty"], 2)} {n["base"]} po cijeni od {round(n["price"], 2)}')
                if n["side"] == "sell":
                    self.agent.sell_narudzbe.remove(n)
                else:
                    self.agent.buy_narudzbe.remove(n)

        async def naruci(self, side: "buy" or "sell", qty: float, price: float):
            base, quote = TRZISTE.split("-")
            narudzba = {
                "id": str(uuid.uuid4()),
                "klijent_jid": self.agent.jid.localpart + "@" + self.agent.jid.domain,
                "type": "limit",
                "side": side,
                "base": base,
                "quote": quote,
                "qty": qty,
                "price": price,
            }

            p = spade.message.Message(
                to=f"knjiga_narudzbi@{IP_PROSODY}",
                body=json.dumps(narudzba),
                metadata={
                    "ontology": "naruci",
                    "performative": "inform"
                })

            await self.send(p)
            if side == "buy":
                self.agent.buy_narudzbe.append(narudzba)
            else:
                self.agent.sell_narudzbe.append(narudzba)


if __name__ == "__main__":
    klijent = MarketBot(f"marketbot@{IP_PROSODY}", "tajna")
    klijent.start().result()

    while klijent.is_alive():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            klijent.stop()
            break
