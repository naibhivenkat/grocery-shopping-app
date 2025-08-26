package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.ImageButton
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.utils.SessionManager
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.ApiService
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ManageItemsActivity : AppCompatActivity() {

    private lateinit var itemAdapter: ItemAdapter
    private lateinit var itemList: MutableList<Item>
    private lateinit var rvItems: RecyclerView
    private lateinit var btnAddItem: Button
    private lateinit var btnBack: ImageButton
    private lateinit var btnRefresh: ImageButton

    private val api = RetrofitClient.instance.create(ApiService::class.java)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_manage_items)

        rvItems = findViewById(R.id.rv_items)
        btnAddItem = findViewById(R.id.btn_add_item)
        btnBack = findViewById(R.id.btn_back)
        btnRefresh = findViewById(R.id.btn_refresh)

        itemList = mutableListOf()
        itemAdapter = ItemAdapter(itemList) { selectedItem ->
            val intent = Intent(this, UpdateItemActivity::class.java)
            intent.putExtra("item", selectedItem)  // FIXED LINE
            startActivity(intent)
        }


        rvItems.layoutManager = LinearLayoutManager(this)
        rvItems.adapter = itemAdapter

        fetchItems()

        btnAddItem.setOnClickListener {
            val intent = Intent(this, AddItemsActivity::class.java)
            startActivity(intent)
        }

        btnRefresh.setOnClickListener {
            finish()
            startActivity(intent) // Clean re-load
        }

        btnBack.setOnClickListener {
            onBackPressed()
        }
    }

    private fun fetchItems() {
        val shopId = SessionManager.getShopId(this)
        Log.d("ManageItemsActivity", "Fetching items for shopId: $shopId")
        val call = api.getItems(shopId.toString())

        call.enqueue(object : Callback<List<Item>> {
            override fun onResponse(call: Call<List<Item>>, response: Response<List<Item>>) {
                if (response.isSuccessful) {
                    itemList.clear()
                    itemList.addAll(response.body() ?: emptyList())
                    itemAdapter.notifyDataSetChanged()
                } else {
                    Toast.makeText(this@ManageItemsActivity, "Failed to load items", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<List<Item>>, t: Throwable) {
                Toast.makeText(this@ManageItemsActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    override fun onResume() {
        super.onResume()
        fetchItems()
    }
}
