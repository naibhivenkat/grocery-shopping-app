package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.bumptech.glide.Glide
import com.example.groceryshoppingapp.adapters.ShopkeeperItemAdapter
import com.example.groceryshoppingapp.models.*
import com.example.groceryshoppingapp.network.ApiClient
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.gson.Gson
import java.io.InputStreamReader
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class AddItemsActivity : AppCompatActivity() {

    private lateinit var spinnerCategory: Spinner
    private lateinit var spinnerItem: Spinner
    private lateinit var etItemDescription: EditText
    private lateinit var btnAddItem: Button
    private lateinit var btnFinish: Button
    private lateinit var recyclerViewItems: androidx.recyclerview.widget.RecyclerView
    private lateinit var itemImage: ImageView

    private val itemDataList = mutableListOf<Item>()
    private lateinit var groceryData: GroceryData
    private lateinit var itemAdapter: ShopkeeperItemAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_add_items)

        spinnerCategory = findViewById(R.id.spinnerCategory)
        spinnerItem = findViewById(R.id.spinnerItem)
        etItemDescription = findViewById(R.id.etItemDescription)
        btnAddItem = findViewById(R.id.btnAddItem)
        btnFinish = findViewById(R.id.btnFinish)
        recyclerViewItems = findViewById(R.id.recyclerViewItems)
        itemImage = findViewById(R.id.itemImage)

        // RecyclerView setup
        itemAdapter = ShopkeeperItemAdapter(itemDataList) {}
        recyclerViewItems.layoutManager = LinearLayoutManager(this)
        recyclerViewItems.adapter = itemAdapter

        loadItemsFromAssets()
        setupCategorySpinner()
        setupAddButton()
        setupFinishButton()
    }

    private fun loadItemsFromAssets() {
        val inputStream = assets.open("data/grocery_items.json")
        val reader = InputStreamReader(inputStream)
        groceryData = Gson().fromJson(reader, GroceryData::class.java)
        reader.close()
    }

    private fun setupCategorySpinner() {
        val categories = groceryData.categories.map { it.name }
        val categoryAdapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, categories)
        categoryAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinnerCategory.adapter = categoryAdapter

        spinnerCategory.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val selectedCategory = groceryData.categories[position]
                setupItemSpinner(selectedCategory)
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    private fun setupItemSpinner(category: Category) {
        val itemNames = category.items.map { it.name }
        val itemAdapterSpinner = ArrayAdapter(this, android.R.layout.simple_spinner_item, itemNames)
        itemAdapterSpinner.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinnerItem.adapter = itemAdapterSpinner

        spinnerItem.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val selectedItem = category.items[position]
                etItemDescription.setText(selectedItem.description)

                if (!selectedItem.image.isNullOrEmpty()) {
                    itemImage.visibility = View.VISIBLE
                    Glide.with(this@AddItemsActivity)
                        .load("file:///android_asset/${selectedItem.image}")
                        .centerCrop()
                        .into(itemImage)
                } else {
                    itemImage.visibility = View.GONE
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    private fun setupAddButton() {
        btnAddItem.setOnClickListener {
            val name = spinnerItem.selectedItem?.toString()?.trim()
            val description = etItemDescription.text.toString().trim()

            if (name.isNullOrEmpty()) {
                Toast.makeText(this, "Select an item", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val shopId = SessionManager.getShopId(this)
            if (shopId.isNullOrEmpty()) {
                Toast.makeText(this, "Shop ID missing", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val selectedCategory = groceryData.categories[spinnerCategory.selectedItemPosition]
            val selectedItem = selectedCategory.items[spinnerItem.selectedItemPosition]

            val item = Item(
                id = "",
                name = name,
                description = description,
                price = 0.0,
                stockQuantity = 0.0,
                shopid = shopId,
                imageUrl = selectedItem.image
            )
            itemDataList.add(item)
            itemAdapter.notifyDataSetChanged()
        }
    }

    private fun setupFinishButton() {
        btnFinish.setOnClickListener {
            if (itemDataList.isEmpty()) {
                Toast.makeText(this, "No items to save", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val shopId = SessionManager.getShopId(this)
            val request = AddItemsRequest(shopId!!, itemDataList)

            val apiService = ApiClient.getApiService(this)
            apiService.addItems(request).enqueue(object : Callback<ApiResponse> {
                override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
                    if (response.isSuccessful && response.body()?.success == true) {
                        Toast.makeText(this@AddItemsActivity, "✅ Items added successfully!", Toast.LENGTH_SHORT).show()
                        SessionManager.setHasItemsAdded(this@AddItemsActivity, true)
                        startActivity(Intent(this@AddItemsActivity, ShopOwnerDashboardActivity::class.java))
                        finish()
                    } else {
                        Toast.makeText(this@AddItemsActivity, "❌ Failed: ${response.body()?.message}", Toast.LENGTH_SHORT).show()
                    }
                }
                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                    Toast.makeText(this@AddItemsActivity, "⚠️ Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }
}
