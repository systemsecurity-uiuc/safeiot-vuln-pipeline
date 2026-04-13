#!/usr/bin/env node
/**
 * Virtual OnOff Light device for UMCCI Checker — Flaw Type 4 demo.
 * Stripped down from matter.js OnOff example; no CLI command execution.
 */

import {
    DeviceTypeId,
    Endpoint,
    Environment,
    Logger,
    ServerNode,
    StorageService,
    Time,
    VendorId,
} from "@matter/main";
import { OnOffLightDevice } from "@matter/main/devices";

const logger = Logger.get("DeviceNode");

async function main() {
    const environment = Environment.default;
    const storageService = environment.get(StorageService);
    console.log(`Storage location: ${storageService.location} (Directory)`);

    const deviceStorage = (await storageService.open("device")).createContext("data");

    const passcode =
        environment.vars.number("passcode") ?? (await deviceStorage.get("passcode", 20202021));
    const discriminator =
        environment.vars.number("discriminator") ?? (await deviceStorage.get("discriminator", 3840));
    const vendorId =
        environment.vars.number("vendorid") ?? (await deviceStorage.get("vendorid", 0xfff1));
    const productId =
        environment.vars.number("productid") ?? (await deviceStorage.get("productid", 0x8000));
    const port = environment.vars.number("port") ?? 5542;
    const uniqueId =
        environment.vars.string("uniqueid") ??
        (await deviceStorage.get("uniqueid", Time.nowMs())).toString();

    await deviceStorage.set({ passcode, discriminator, vendorid: vendorId, productid: productId, uniqueid: uniqueId });

    const server = await ServerNode.create({
        id: uniqueId,
        network: { port },
        commissioning: { passcode, discriminator },
        productDescription: {
            name: "UMCCI OnOff Light",
            deviceType: DeviceTypeId(OnOffLightDevice.deviceType),
        },
        basicInformation: {
            vendorName: "umcci-demo",
            vendorId: VendorId(vendorId),
            nodeLabel: "UMCCI OnOff Light",
            productName: "UMCCI OnOff Light",
            productLabel: "UMCCI OnOff Light",
            productId,
            serialNumber: `umcci-${uniqueId}`,
            uniqueId,
        },
    });

    const endpoint = new Endpoint(OnOffLightDevice, { id: "onoff" });
    await server.add(endpoint);

    endpoint.events.onOff.onOff$Changed.on(value => {
        console.log(`OnOff is now ${value ? "ON" : "OFF"}`);
    });

    logger.info(server);
    await server.run();
}

main().catch(error => console.error(error));
