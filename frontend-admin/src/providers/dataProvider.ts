import axios from "axios";
import simpleRest from "@refinedev/simple-rest";

const httpClient = axios.create({ withCredentials: true });

export const dataProvider = simpleRest("/api/admin", httpClient);
