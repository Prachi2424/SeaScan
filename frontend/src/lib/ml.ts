import { Client, handle_file } from "@gradio/client";

export interface OilSpillPrediction {
  prediction: "Oil_Spill" | "No_Oil";
  class_id: number;
  confidence: number;
  oil_spill_probability: number;
}

let clientPromise: Promise<Client> | null = null;

function getClient(): Promise<Client> {
  if (!clientPromise) {
    clientPromise = Client.connect("tanyajain/SeaScan");
  }

  return clientPromise;
}

export async function predictOilSpill(
  file: File,
): Promise<OilSpillPrediction> {
  const client = await getClient();

  const result = await client.predict("/predict", {
    image: handle_file(file),
  });

  // Gradio types result.data as unknown.
  // The Space's /predict endpoint returns one JSON object.
  const dataArray = result.data as unknown[];

  const value = dataArray[0];

  if (typeof value !== "object" || value === null) {
    throw new Error("Unexpected response from SeaScan ML model.");
  }

  const data = value as Record<string, unknown>;

  return {
    prediction: data.prediction as "Oil_Spill" | "No_Oil",
    class_id: Number(data.class_id),
    confidence: Number(data.confidence),
    oil_spill_probability: Number(data.oil_spill_probability),
  };
}