Set the REPLICATE_API_TOKEN environment variable

export REPLICATE_API_TOKEN=r8_3gP**********************************

Visibility

Copy
Learn more about authentication

Install Replicate’s Python client library

pip install replicate

Copy
Learn more about setup
Run salesforce/blip using Replicate’s API. Check out the model's schema for an overview of inputs and outputs.

import replicate

input = {
    "image": "https://replicate.delivery/mgxm/f4e50a7b-e8ca-432f-8e68-082034ebcc70/demo.jpg"
}

output = replicate.run(
    "salesforce/blip:2e1dddc8621f72155f24cf2e0adbde548458d3cab9f00c0139eea840d0ac4746",
    input=input
)
print(output)