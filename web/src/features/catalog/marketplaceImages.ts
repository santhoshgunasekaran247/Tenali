const photo = (id: string, width: number) => `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${width}&q=80`;

export const MARKETPLACE_IMAGES = {
  hero: photo("photo-1490481651871-ab68de25d43d", 1100),
  story: photo("photo-1490312278390-ab64016e0aa9", 900),
  collection: photo("photo-1539109136881-3be0616acf4b", 900),
};
