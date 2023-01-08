#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pprint import pprint
import spade
import time
import random
import asyncio
import json
from datetime import datetime
from konfiguracija import IP_PROSODY, TRZISTE
from helpers import green_text, red_text


class Mjenjacnica(spade.agent.Agent):
    limit = {"buy": [], "sell": []}
    pretplaceni = []
    buy_price = 0

    def daj_cijene(self):
        if len(self.limit["sell"]) > 0:
            sell = self.limit["sell"][0]["price"]
        else:
            sell = 0
        if len(self.limit["buy"]) > 0:
            buy = self.limit["buy"][0]["price"]
        else:
            buy = 0
        return {"buy": buy, "sell": sell}

    async def setup(self):
        naruci_template = spade.template.Template()
        naruci_template.set_metadata("ontology", "naruci")
        self.add_behaviour(self.OdgovarajNaNarudzbe(), naruci_template)
        otkazi_template = spade.template.Template()
        otkazi_template.set_metadata("ontology", "otkazi")
        self.add_behaviour(self.OdgovarajNaOtkazaneNarudzbe(), otkazi_template)
        pretplata_cijene_template = spade.template.Template()
        pretplata_cijene_template.set_metadata(
            "ontology", "pretplati-na-cijene")
        self.add_behaviour(self.PretplacujNaCijene(),
                           pretplata_cijene_template)

    class PretplacujNaCijene(spade.behaviour.CyclicBehaviour):
        async def run(self):
            p = await self.receive(timeout=100)
            if p:
                self.agent.pretplaceni.append(p.body)
                await self.posalji_cijene(p.body)

        async def posalji_cijene(self, pretplatnik):
            cijene = self.agent.daj_cijene()
            await self.send(spade.message.Message(
                to=pretplatnik,
                body=json.dumps(cijene),
                metadata={"ontology": "pretplata-cijene"},
            ))

    class OdgovarajNaOtkazaneNarudzbe(spade.behaviour.CyclicBehaviour):
        async def run(self):
            p = await self.receive(timeout=100)
            if p:
                narudzba = json.loads(p.body)
                await self._otkazi_narudzbu(narudzba)
                self.agent._ispisi_knjigu()

        async def _otkazi_narudzbu(self, narudzba):
            side = narudzba["side"]
            self.agent.limit[side] = [
                n for n in self.agent.limit[side] if n["id"] != narudzba["id"]]
            await self.posalji_cijene()

        async def posalji_cijene(self):
            for pretplaceni in self.agent.pretplaceni:
                cijene = self.agent.daj_cijene()
                await self.send(spade.message.Message(
                    to=pretplaceni,
                    body=json.dumps(cijene),
                    metadata={"ontology": "pretplata-cijene"},
                ))

    class OdgovarajNaNarudzbe(spade.behaviour.CyclicBehaviour):
        async def run(self):
            p = await self.receive(timeout=100)
            if p:
                narudzba = json.loads(p.body)
                narudzba["executed"] = 0
                narudzba["status"] = "pending"
                narudzba["created_at"] = datetime.now().timestamp()
                narudzba["executions"] = []

                await self._obradi_narudzbu(narudzba)
                self.agent._ispisi_knjigu()
                await self.posalji_cijene()

        async def posalji_cijene(self):
            for pretplaceni in self.agent.pretplaceni:
                cijene = self.agent.daj_cijene()
                await self.send(spade.message.Message(
                    to=pretplaceni,
                    body=json.dumps(cijene),
                    metadata={"ontology": "pretplata-cijene"},
                ))

        async def _obradi_narudzbu(self, narudzba):
            side = narudzba["side"]
            if side == "buy":
                await self._obradi_limit_buy(narudzba)
            else:
                await self._obradi_limit_sell(narudzba)

        async def _obradi_limit_buy(self, narudzba):
            sells = self.agent.limit["sell"]
            n = len(sells)
            if n != 0:
                for sell in sells[:]:
                    if sell["price"] < narudzba["price"]:
                        buy_to_execute = narudzba["qty"] - narudzba["executed"]
                        sell_to_execute = sell["qty"] - sell["executed"]
                        fillable = min(buy_to_execute, sell_to_execute)

                        narudzba["executed"] += fillable
                        sell["executed"] += fillable

                        narudzba_execution = {
                            "price": sell["price"],
                            "qty": fillable,
                            "total_filled": narudzba["executed"],
                        }

                        sell_execution = {
                            "price": sell["price"],
                            "qty": fillable,
                            "total_filled": sell["executed"],
                        }

                        narudzba["executions"].append(narudzba_execution)
                        sell["executions"].append(sell_execution)

                        if sell["executed"] == sell["qty"]:
                            await self._obavijesti_execution(sell, sell_execution)
                            self._remove_limit_order(sell["id"], "sell")
                        if narudzba["executed"] == narudzba["qty"]:
                            await self._obavijesti_execution(narudzba, narudzba_execution)
                            return
                    else:
                        return self._dodaj_limit_buy(narudzba)
            else:
                return self._dodaj_limit_buy(narudzba)

        async def _obradi_limit_sell(self, narudzba):
            buys = self.agent.limit["buy"]
            n = len(buys)
            if n != 0:
                for buy in buys[:]:
                    if buy["price"] > narudzba["price"]:
                        sell_to_execute = narudzba["qty"] - \
                            narudzba["executed"]
                        buy_to_execute = buy["qty"] - buy["executed"]
                        fillable = min(buy_to_execute, sell_to_execute)

                        narudzba["executed"] += fillable
                        buy["executed"] += fillable

                        narudzba_execution = {
                            "price": narudzba["price"],
                            "qty": fillable,
                            "total_filled": narudzba["executed"],
                        }

                        buy_execution = {
                            "price": narudzba["price"],
                            "qty": fillable,
                            "total_filled": buy["executed"],
                        }

                        narudzba["executions"].append(narudzba_execution)
                        buy["executions"].append(buy_execution)

                        if buy["executed"] == buy["qty"]:
                            await self._obavijesti_execution(buy, buy_execution)
                            self._remove_limit_order(buy["id"], "buy")
                        if narudzba["executed"] == narudzba["qty"]:
                            await self._obavijesti_execution(narudzba, narudzba_execution)
                            return
                    else:
                        return self._dodaj_limit_sell(narudzba)
            else:
                return self._dodaj_limit_sell(narudzba)

        def _dodaj_limit_buy(self, narudzba):
            n = len(self.agent.limit["buy"])
            if n == 0:
                return self.agent.limit["buy"].append(narudzba)
            for i in range(n):
                if narudzba["price"] > self.agent.limit["buy"][i]["price"]:
                    self.agent.limit["buy"].insert(i, narudzba)
                    return

        def _dodaj_limit_sell(self, narudzba):
            n = len(self.agent.limit["sell"])
            if n == 0:
                return self.agent.limit["sell"].append(narudzba)
            for i in range(n):
                if narudzba["price"] < self.agent.limit["sell"][i]["price"]:
                    self.agent.limit["sell"].insert(i, narudzba)
                    return

        def _remove_limit_order(self, Id, t):
            for i in range(len(self.agent.limit[t])):
                if self.agent.limit[t][i]["id"] == Id:
                    del self.agent.limit[t][i]
                    return

        async def _obavijesti_execution(self, narudzba, execution):
            order_id = narudzba["id"]
            primatelj = narudzba["klijent_jid"]
            body = json.dumps(execution | {"order_id": order_id})
            p = spade.message.Message(
                to=primatelj,
                body=body,
                metadata={
                    "ontology": "execution",
                    "performative": "inform"
                })

            pprint(execution)

            await self.send(p)

    def _ispisi_knjigu(self):
        print(f"\n{TRZISTE}")
        print("|{:<31}Ponuda{:<35}|".format("-" * 31, "-" * 35))
        print("|{:<16} {:<16} {:<11} {:<26}|".format(
            "Cijena", "Količina", "Vrijeme", "Klijent"))

        for order in self.limit["sell"][::-1]:
            print("|{:<25} {:<16} {:<11} {:<26}|".format(
                red_text(round(order["price"], 2)),
                round(order["qty"] - order["executed"], 2),
                datetime.fromtimestamp(
                    order["created_at"]).strftime("%T.%f")[:-4],
                order["klijent_jid"]
            ))

        for order in self.limit["buy"]:
            print("|{:<25} {:<16} {:<11} {:<26}|".format(
                green_text(round(order["price"], 2)),
                round(order["qty"] - order["executed"], 2),
                datetime.fromtimestamp(
                    order["created_at"]).strftime("%T.%f")[:-4],
                order["klijent_jid"]
            ))

        print("|{:<30}Potražnja{:<33}|".format("-" * 30, "-" * 33))


if __name__ == "__main__":
    mjenjacnica = Mjenjacnica(f"knjiga_narudzbi@{IP_PROSODY}", "tajna")
    mjenjacnica.start().result()

    while mjenjacnica.is_alive():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            mjenjacnica.stop()
            break
